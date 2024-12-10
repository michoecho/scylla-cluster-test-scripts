import asyncio
import shlex
import os
from typing import List, Dict, Sequence
import yaml
import json
import subprocess
import urllib.parse

def load_yaml(stream):
    return yaml.load(stream, Loader=yaml.SafeLoader)
def dump_yaml(stream):
    return yaml.dump(stream, Dumper=yaml.SafeDumper)

def load_inventory(deployment_name):
    inventory_yaml = subprocess.run(['bin/ansible-inventory', deployment_name, '--list', '--yaml'], check=True, capture_output=True).stdout
    return load_yaml(inventory_yaml)["all"]["children"]

async def run(command: Sequence[str], stdin_data=None, **kwargs):
    try:
        proc = await asyncio.create_subprocess_exec(*command, **kwargs);
        stdout, stderr = await proc.communicate(stdin_data)
        return stdout, stderr, proc.returncode
    except asyncio.exceptions.CancelledError:
        proc.terminate()
        raise

async def check_output(command: Sequence[str]):
    stdout, stderr, returncode = await run(command, stdout=asyncio.subprocess.PIPE)
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, command, stdout)
    return stdout

def fair_split_point(n, k, i):
    return (n // k * i) + min(i, n % k)

async def clean_cancel(task):
    try:
        task.cancel()
        await task
    except asyncio.CancelledError:
        pass

class Deployment:
    def __init__(self, name):
        self.name = name
        self.inventory = load_inventory(name)
        self.server_hosts = self.inventory.get("server", {}).get("hosts", {})
        self.client_hosts = self.inventory.get("client", {}).get("hosts", {})
        self.monitor_host = next(iter(self.inventory["monitor"]["hosts"]))

    async def ssh(self, host, command: str, stdout=None, stderr=None, stdin_data=None):
        return await run(["bin/ssh", self.name, host, command], stdin=asyncio.subprocess.PIPE, stdout=stdout, stderr=stderr, stdin_data=stdin_data);
    async def ssh_relogin(self, host):
        return await run(["bin/ssh", self.name, "-Ostop", host])
    async def ssh_output(self, host, command: str, stdin=None, stdout=None, stderr=None):
        return await check_output(["bin/ssh", self.name, host, command])
    async def pssh(self, hosts: Sequence[str], command: str, stdout=None, stderr=None):
        await asyncio.gather(*[self.ssh(host, command) for host in hosts])

    async def wait_for_cql(self, host):
        cmd = 'until grep -q "^[^:]*:9042" <(ss -tln); do sleep 1; done'
        await self.ssh(host, cmd)

    async def wait_for_machine_image(self):
        cmd = 'until test -e /etc/scylla/machine_image_configured; do sleep 1; done'
        await self.pssh(self.server_hosts, cmd)

    async def configure_prometheus_yaml(self):
        path = "scylla-monitoring/prometheus/prometheus.yml.template"
        await self.ssh(self.monitor_host, fr"sed -i {path} -e 's/^  scrape_interval:.*$/  scrape_interval: 1s/'")
        await self.ssh(self.monitor_host, fr"sed -i {path} -e 's/^  scrape_timeout:.*$/  scrape_timeout: 1s/'")

        path = "scylla-monitoring/grafana/datasource.yml"
        await self.ssh(self.monitor_host, fr"sed -i {path} -e 's/^    timeInterval:.*$/    timeInterval: '\'1s\''/'")

    async def configure_scylla_yaml(self, extra_opts={}):
        yamls_raw = await asyncio.gather(*[self.ssh_output(k, "cat /etc/scylla/scylla.yaml") for k in self.server_hosts])
        yamls = list(zip(self.server_hosts.items(), (load_yaml(x) for x in yamls_raw)))
        for (k, v), y in yamls:
            y["seed_provider"][0]["parameters"][0]["seeds"] = v["seed"]
            y["cluster_name"] = "sso-cluster"
            if v["private_ip"] == v["seed"]:
                y["ring_delay_ms"] = 1
                y["skip_wait_for_gossip_to_settle"] = 0
            else: 
                y["ring_delay_ms"] = 10000
            y["enable_tablets"] = "true"
            y.update(extra_opts)
        await asyncio.gather(*[self.ssh(k, "sudo tee /etc/scylla/scylla.yaml >/dev/null", stdin_data=dump_yaml(y).encode("utf-8")) for (k, v), y in yamls])
        await self.pssh(self.server_hosts, "sudo pkill -SIGHUP scylla")

    async def setup_monitor(self):
        aptget = "apt-get -oDPkg::Lock::Timeout=-1"
        command = f"""sudo bash <<EOF
               {aptget} update
               {aptget} install -y docker.io unzip wget fish
               #python3 -m pip install pyyaml
               #python3 -m pip install -I -U psutil
               systemctl start docker 
               usermod -aG docker $USER
        \nEOF"""
        await self.ssh(self.monitor_host, command)
        await self.ssh_relogin(self.monitor_host)
        command = """bash <<EOF
            git -C scylla-monitoring fetch -q origin || git clone -q https://github.com/scylladb/scylla-monitoring
            git -C scylla-monitoring checkout -q 4.8.3
        \nEOF"""
        await self.ssh(self.monitor_host, command)
        config = [{
            "targets": [f'{v["private_ip"]}:9180' for v in self.server_hosts.values()],
            "labels": {"cluster": "cluster1", "dc": "dc1"},
        }]
        await self.ssh(self.monitor_host, "cd scylla-monitoring; ./kill-all.sh")
        await self.configure_prometheus_yaml()
        await self.ssh(self.monitor_host, "tee scylla-monitoring/prometheus/scylla_servers.yml >/dev/null", stdin_data=dump_yaml(config).encode("utf-8"))
        await self.ssh(self.monitor_host, "cd scylla-monitoring; ./start-all.sh -d ../data -v 2024.2 -b --web.enable-admin-api --no-loki --no-renderer")

    async def setup_clients(self):
        aptget = "apt-get -oDPkg::Lock::Timeout=-1"
        command = f"""sudo bash -xeu <<EOF
               {aptget} update
               {aptget} install -y openjdk-11-jre fish
               wget https://github.com/scylladb/cassandra-stress/releases/download/v3.17.0/cassandra-stress-3.17.0-bin.tar.gz
               tar xf cassandra-stress*.tar.gz
        \nEOF"""
        await asyncio.gather(
            self.pssh(self.client_hosts, command),
        )

    async def setup_servers(self):
        aptget = "apt-get -oDPkg::Lock::Timeout=-1"
        command = f"""sudo bash -xeu <<EOF
               {aptget} update
               {aptget} install -y linux-tools-common linux-tools-$(uname -r) blktrace fio fish rsync less openjdk-11-jre-headless lttng-tools htop
        \nEOF"""
        await self.pssh(self.server_hosts, command)

    async def rsync(self, src, dest, *options):
        await run(["rsync", *options, "-r", "-e", f"bin/ssh {self.name}", src, dest])

    async def collect(self, hosts: Sequence[str], src, dest_dir, *options):
        await run(["mkdir", "-p", dest_dir])
        await asyncio.gather(*[self.rsync(f"{host}:{src}", f"{dest_dir}/{host}/", "--mkpath", *options) for host in hosts])

    async def stop_cs(self, /, client_hosts: Sequence[str] = None):
        client_hosts = client_hosts or self.client_hosts
        await self.pssh(client_hosts, "pkill --full org.apache.cassandra.stress")

    async def cs(self, /, options, server_hosts: Sequence[str] = None, client_hosts: Sequence[str] = None, cs = "cassandra-stress"):
        server_hosts = server_hosts or self.server_hosts
        client_hosts = client_hosts or self.client_hosts
        await self.pssh(client_hosts, "pkill --full org.apache.cassandra.stress")
        node = "-node {}".format(','.join(v["private_ip"] for v in server_hosts.values()))
        mode = "-mode native cql3 protocolVersion=4 maxPending=4096"
        command = f"{cs} {options} {node} {mode}"
        await self.pssh(client_hosts, command)

    async def populate(self, /, n_rows, options, server_hosts: Sequence[str] = None, client_hosts: Sequence[str] = None, cs = "cassandra-stress", tablets: bool = False):
        server_hosts = server_hosts or self.server_hosts
        client_hosts = client_hosts or self.client_hosts
        await self.pssh(client_hosts, f"pkill --full org.apache.cassandra.stress")

        n = n_rows
        k = len(client_hosts)
        ranges = [(fair_split_point(n, k, i), fair_split_point(n, k, i+1)) for i in range(k)]

        node = "-node {}".format(','.join(self.server_hosts[server]["private_ip"] for server in server_hosts))
        mode = "-mode native cql3 protocolVersion=4 maxPending=4096"

        (server_0_name, server_0_vars) = next(iter(self.server_hosts.items()))
        
        if tablets:
            await self.ssh(server_0_name, f'''cqlsh -e "CREATE KEYSPACE keyspace1 WITH replication = {{'class': 'NetworkTopologyStrategy', 'replication_factor': 3}} AND TABLETS = {{'enabled': true, 'initial': 64}}" {server_0_vars["private_ip"]}''')

        # Create schema.
        await self.ssh(next(iter(self.client_hosts)), f'{cs} write no-warmup cl=ALL n=1 -pop seq=1..1 {node} {mode} {options} >/dev/null')
        await self.ssh(server_0_name, f'cqlsh -e "ALTER KEYSPACE keyspace1 WITH DURABLE_WRITES = false;" {server_0_vars["private_ip"]}')
        await asyncio.gather(*[
            self.ssh(host, f'{cs} write no-warmup cl=ALL n={range_end-range_start} -pop seq={range_start+1}..{range_end} {node} {mode} {options}')
            for (host, (range_start, range_end)) in zip(self.client_hosts, ranges)
        ])
        await self.ssh(server_0_name, f'cqlsh -e "ALTER KEYSPACE keyspace1 WITH DURABLE_WRITES = true;" {server_0_vars["private_ip"]}')

    async def start_cluster(self, server_hosts: Sequence[str] = None):
        server_hosts = {x: self.server_hosts[x] for x in (server_hosts or self.server_hosts)}
        seed = next(k for (k, v) in server_hosts.items() if v["private_ip"] == v["seed"])
        non_seeds = [x for x in server_hosts if x != seed]
        await self.ssh(seed, 'sudo systemctl start scylla-server')
        await self.wait_for_cql(seed)
        # Does it really have to be sequential?
        for x in non_seeds:
            await self.ssh(x, 'sudo systemctl start scylla-server')
            await self.wait_for_cql(x)

    async def start_nodes_in_parallel(self, server_hosts: Sequence[str] = None):
        server_hosts = {x: self.server_hosts[x] for x in (server_hosts or self.server_hosts)}
        await self.pssh(server_hosts, 'sudo systemctl start scylla-server')
        for x in server_hosts:
            await self.wait_for_cql(x)

    async def stop_cluster(self):
        await self.pssh(self.server_hosts, 'sudo systemctl stop scylla-server')

    async def reset_cluster(self):
        await self.pssh(self.server_hosts, """
            sudo bash <<EOF
            shopt -s extglob
            systemctl stop scylla-server
            rm -rf /var/lib/scylla/!(backup)
            sudo mkdir /var/lib/scylla/{data,hints,view_hints,commitlog}
            sudo chown scylla /var/lib/scylla/{data,hints,view_hints,commitlog}
            \nEOF""")

    async def download_metrics(self, dest_dir):
        response = await self.ssh_output(self.monitor_host, "curl --silent -XPOST http://localhost:9090/api/v1/admin/tsdb/snapshot")
        snapshot_name = json.loads(response.decode("utf-8"))["data"]["name"]
        await self.rsync(f'{self.monitor_host}:data/snapshots/{snapshot_name}/', f"{dest_dir}/data", "--mkpath")

    async def clean_metrics(self):
        # %2B is * in URL encoding, so '__name__=~".%2B"' means 'any name'
        await self.ssh(self.monitor_host, """curl --silent -X POST -g 'http://localhost:9090/api/v1/admin/tsdb/delete_series?match[]={__name__=~".%2B"}'""")

    async def query_prometheus(self, query_string):
        url = f"http://localhost:9090/api/v1/query"
        response = await self.ssh_output(self.monitor_host, f"curl --silent {shlex.quote(url)} --data-urlencode query={shlex.quote(query_string)}")
        return json.loads(response.decode("utf-8"))

    async def wait_for_compaction_end(self, poll_period=20, required_good_polls=3):
        query_string=r'sum(scylla_compaction_manager_compactions{})'
        print(f'Waiting for all compactions to end. Checking every {poll_period}s, waiting for 3 consecutive zero results:')
        good_polls = 0
        while True:
            response = await self.query_prometheus(query_string)
            #print(response)
            ongoing_compactions = int(response["data"]["result"][0]["value"][1])
            print(f'Number of ongoing compactions: {ongoing_compactions}')
            if ongoing_compactions == 0:
                good_polls += 1
            else:
                good_polls = 0
            if good_polls >= required_good_polls:
                break
            else:
                await asyncio.sleep(poll_period)

    async def wait_for_long_queue(self):
        query_string=r'max(scylla_io_queue_queue_length{class="sl:default"})'
        poll_period=0.5
        print(f'Waiting for long sl:default IO queue. Checking every {poll_period}s:')
        while True:
            response = await self.query_prometheus(query_string)
            print(response)
            result = int(response["data"]["result"][0]["value"][1])
            print(f'Queue length: {result}')
            if result > 80:
                break
            await asyncio.sleep(poll_period)

    async def quiesce(self):
        await self.pssh(self.server_hosts, "nodetool flush")
        await self.wait_for_compaction_end()

    async def backup_data(self):
        await self.pssh(self.server_hosts, """
            sudo bash <<EOF
            shopt -s extglob
            systemctl stop scylla-server
            rm -rf /var/lib/scylla/backup
            mkdir /var/lib/scylla/backup
            sudo cp -aR --reflink=auto /var/lib/scylla/!(backup) /var/lib/scylla/backup/
            \nEOF""")

    async def restore_data(self):
        await self.pssh(self.server_hosts, """
            sudo bash <<EOF
            shopt -s extglob
            systemctl stop scylla-server
            rm -rf /var/lib/scylla/!(backup)
            sudo cp -aR --reflink=auto /var/lib/scylla/backup/* /var/lib/scylla/
            sudo mkdir /var/lib/scylla/{data,hints,view_hints,commitlog}
            sudo chown scylla /var/lib/scylla/{data,hints,view_hints,commitlog}
            \nEOF""")
