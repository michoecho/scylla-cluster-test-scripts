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

async def setup_cluster():
    await d.wait_for_machine_image()
    await d.configure_scylla_yaml()
    await d.start_cluster()
    await d.populate(
        cs="JAVA_HOME=/usr/lib/jvm/java-1.8.0 cassandra-stress",
        n_rows=1000000000,
        options="-rate threads=200 -schema 'replication(strategy=SimpleStrategy,replication_factor=3)' -col 'size=FIXED(1024)' 'n=FIXED(1)'",
    )
    await d.quiesce()
    await d.stop_cluster()
    await d.backup_data()

async def prepare():
    await asyncio.gather(setup_cluster(), d.setup_monitor())

async def run():
    datetime_now_string = datetime.now().replace(microsecond=0).isoformat().replace(":", "-")
    trial_dir = "trials/{}/{}".format(dname, datetime_now_string)

    async def get_metrics():
        await d.stop_cluster()
        metrics_dir = os.path.join(trial_dir, "monitoring")
        await d.download_metrics(metrics_dir)

    async def get_summary(sub):
        warmup_seconds = 60
        cooldown_seconds = 10
        stat_dir = os.path.join(trial_dir, f"cassandra-stress: {sub}")
        await d.collect(d.client_hosts, "log.hdr", stat_dir)
        return await bench.hdr.process_hdr_file_set(stat_dir, "log", java="/usr/lib/jvm/java-1.8.0/bin/java", time_start=warmup_seconds, time_end=duration-cooldown_seconds)

    duration = 60 * 60
    for throttle, op in [(15000, "write"), (10000, "read"), (9000, "mixed 'ratio(write=1,read=1)'")]:
        await d.cs(
            cs="JAVA_HOME=/usr/lib/jvm/java-1.8.0 cassandra-stress",
            options = f"{op} duration='{duration}s' cl=QUORUM -rate threads=100 throttle={throttle}/s -log hdrfile=log.hdr -pop 'dist=gauss(1..1000000000,500000000,50000000)' -schema 'replication(strategy=SimpleStrategy,replication_factor=3)' -col 'size=FIXED(1024)' 'n=FIXED(1)'",
        )
        await get_summary(op)
    await get_metrics()

async def full():
    await prepare()
    await d.stop_cluster()
    await asyncio.gather(d.clean_metrics(), d.restore_data())
    await d.start_cluster()
    await run()
asyncio.run(full())
