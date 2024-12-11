import asyncio
import shlex
import os
import sys
from textwrap import dedent
import bench.hdr, bench.utils
from datetime import datetime

dname = sys.argv[1]
assert shlex.quote(dname)
d = bench.utils.Deployment(dname)
schema="-schema replication(strategy=SimpleStrategy,replication_factor=3) -col size='FIXED(1024)' n='FIXED(1)'",
CS="JAVA=$(realpath /usr/lib/jvm/java-11*/bin/java) CLASSPATH=$(echo `ls -1 cas*/lib/*.jar cas*/tools/lib/*.jar` | tr ' ' ':') cas*/tools/bin/cassandra-stress"

async def full():
    #await d.stop_cs()
    #await d.stop_cluster()
    #await d.configure_scylla_yaml()
    #await d.setup_monitor()
    #await d.reset_cluster()
    #await d.start_cluster(list(d.server_hosts)[:3])
    #await d.populate(
    #    cs="JAVA=$(realpath /usr/lib/jvm/java-11*/bin/java) CLASSPATH=$(echo `ls -1 cas*/lib/*.jar cas*/tools/lib/*.jar` | tr ' ' ':') cas*/tools/bin/cassandra-stress",
    #    n_rows=650000000,
    #    options="-rate threads=300 -schema 'replication(strategy=SimpleStrategy,replication_factor=3)' -col 'size=FIXED(128)' 'n=FIXED(8)'",
    #    tablets=True,
    #)
    #await d.backup_data()
    #await asyncio.gather(*[
    #    d.ssh(d.monitor_host, "cd scylla-monitoring; ./kill-all.sh")
    #    d.wait_for_machine_image()
    #])
    #await asyncio.gather(*[
    #    d.setup_monitor(),
    #    d.setup_clients(),
    #    d.setup_servers(),
    #])
    #await d.configure_scylla_yaml()
    #await asyncio.gather(*[d.rsync("fake_io_properties.yaml", f"{s}:/etc/scylla.d/io_properties.yaml", "--rsync-path=sudo rsync") for s in d.server_hosts])
    #await asyncio.gather(*[d.rsync("fake_io.conf", f"{s}:/etc/scylla.d/io.conf", "--rsync-path=sudo rsync") for s in d.server_hosts])
    #await asyncio.gather(*[d.rsync("fake_cpuset.conf", f"{s}:/etc/scylla.d/cpuset.conf", "--rsync-path=sudo rsync") for s in d.server_hosts])
    await d.stop_cs()
    await d.restore_data()
    await d.start_nodes_in_parallel(list(d.server_hosts)[:3])
    await d.cs(
        cs=CS,
        options = f"read no-warmup cl=QUORUM duration=800m -rate threads=300 fixed=24000/s -col 'size=FIXED(128) n=FIXED(8)' -pop 'dist=gauss(1..650000000,325000000,9750000)'",
    )

asyncio.run(full())
