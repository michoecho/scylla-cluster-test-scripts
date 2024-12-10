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
    await asyncio.gather(*[
        d.stop_cs(),
        d.reset_cluster()
    ])

    await asyncio.gather(*[
        d.setup_monitor(),
        d.setup_servers(),
        d.setup_clients(),
        setup_cluster(),
    ])

    await d.start_cluster(list(d.server_hosts)[:3])
    await asyncio.create_task(d.populate(
        cs=CS,
        n_rows=100000000,
        options="-rate threads=300 -schema 'replication(strategy=SimpleStrategy,replication_factor=3)' -col 'size=FIXED(128)' 'n=FIXED(8)'",
        tablets=True,
    ))
    await d.stop_cluster()
    await d.start_nodes_in_parallel(list(d.server_hosts)[:3])
    await asyncio.sleep(30)
    await d.quiesce()
    await d.backup_data()

    #await d.configure_scylla_yaml()
    #await asyncio.gather(*[d.rsync("fake_io_properties.yaml", f"{s}:/etc/scylla.d/io_properties.yaml", "--rsync-path=sudo rsync") for s in d.server_hosts])
    #await asyncio.gather(*[d.rsync("fake_io.conf", f"{s}:/etc/scylla.d/io.conf", "--rsync-path=sudo rsync") for s in d.server_hosts])
    #await asyncio.gather(*[d.rsync("fake_cpuset.conf", f"{s}:/etc/scylla.d/cpuset.conf", "--rsync-path=sudo rsync") for s in d.server_hosts])

asyncio.run(full())
