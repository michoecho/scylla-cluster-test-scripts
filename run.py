import asyncio
import shlex
import os
import sys
from textwrap import dedent
import bench.hdr, bench.utils
from datetime import datetime
from bench.utils import run
import time

dname = sys.argv[1]
assert shlex.quote(dname)
d = bench.utils.Deployment(dname)
schema="-schema replication(strategy=SimpleStrategy,replication_factor=3) -col size='FIXED(1024)' n='FIXED(1)'",
CS="JAVA=$(realpath /usr/lib/jvm/java-11*/bin/java) CLASSPATH=$(echo `ls -1 cas*/lib/*.jar cas*/tools/lib/*.jar` | tr ' ' ':') cas*/tools/bin/cassandra-stress"

async def setup_cluster():
    await d.wait_for_machine_image()
    await d.configure_scylla_yaml()
    await d.start_cluster(list(d.server_hosts)[:3])

async def full():
    await d.stop_cs()
    await d.restore_data()
    await d.start_cluster(list(d.server_hosts)[:3])
    load = asyncio.create_task(d.cs(
        cs=CS,
        options = f"read no-warmup cl=QUORUM duration=800m -rate threads=300 fixed=24000/s -col 'size=FIXED(128) n=FIXED(8)' -pop 'dist=gauss(1..650000000,325000000,9750000)'",
    ))
    await asyncio.sleep(20)

    #sess = datetime.now().replace(microsecond=0).isoformat()
    #await d.pssh(d.server_hosts, f"""
    #    sudo bash <<EOF
    #    lttng-sessiond --daemonize
    #    lttng destroy
    #    lttng create --snapshot {sess}
    #    lttng enable-channel --userspace --session={sess} --subbuf-size=8M --num-subbuf=4 my-channel
    #    lttng enable-event --userspace --session={sess} --channel=my-channel 'seastar:*,scylla:*' --exclude='seastar:poll,seastar:run_task'
    #    lttng start 
    #    \nEOF""")
    bootstrap = asyncio.create_task(d.start_nodes_in_parallel(list(d.server_hosts)[3:]))
    await d.wait_for_long_queue()
    ##await asyncio.sleep(40)
    #await d.pssh(d.server_hosts, f"""
    #    sudo bash <<EOF
    #    rm -r snapshots
    #    mkdir snapshots
    #    lttng snapshot record
    #    mv /root/lttng-traces/{sess}-*/snapshot-1-* snapshots/
    #    chown -R scyllaadm snapshots
    #    \nEOF""")
    await d.pssh(d.server_hosts, f"""
        bash <<EOF
        curl -X POST 127.0.0.1:10000/system/dump_trace
        sudo rm -r ~/snapshots
        mkdir ~/snapshots
        sudo mv /var/lib/scylla/traces/* ~/snapshots
        chown -R scyllaadm snapshots
        \nEOF""")
    await run(["mkdir", "-p", "traces"])
    await d.collect(d.server_hosts, f"snapshots/*", "traces/")
    await bootstrap
    await load

asyncio.run(full())
