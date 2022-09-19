import os
import asyncio
import glob
import shlex
import csv
from collections import namedtuple

async def process_hdr_file_set(dir, name, java, time_start=None, time_end=None):
    p = HdrLogProcessor(java=java, time_start=time_start, time_end=time_end)
    return await p.process_hdr_file_set(dir, name)

class HdrLogProcessor:
    def __init__(self, /, java, time_start, time_end):
        self.dir = dir
        self.java = java
        self.time_start = time_start
        self.time_end = time_end
        self.semaphore = asyncio.Semaphore(2 * len(os.sched_getaffinity(0)))

    async def run(self, *args):
        from bench.utils import run
        async with self.semaphore:
            await run(*args)

    async def process_hdr_file_set(self, dir, name):
        await self.trim_recursively(dir, name)
        await self.merge_recursively(dir, name)
        await self.process_recursively(dir, name)
        return await self.summarize_recursively(dir, name)

    async def trim(self, file):
        file_no_ext = os.path.splitext(file)[0]
        args = f"union -ifp {shlex.quote(file)} -of {shlex.quote(file_no_ext)}.trimmed.hdr"
        if self.time_start is not None:
            args = f'{args} -start {self.time_start}'
        if self.time_end is not None:
            args = f'{args} -end {self.time_end}'
        cmd = f'{self.java} -cp lib/processor.jar CommandDispatcherMain {args}'
        await self.run(shlex.split(cmd))

    async def trim_recursively(self, dir, name):
        files = glob.iglob(f'{dir}/**/{name}.hdr', recursive=True)
        await asyncio.gather(*(self.trim(file) for file in files if not file.endswith("trimmed.hdr")))

    async def merge_recursively(self, dir, name):
        files = glob.iglob(f'{dir}/**/{name}.trimmed.hdr', recursive=True)
        input = " ".join(f"-ifp {shlex.quote(file)}" for file in files)
        cmd = f"{self.java} -cp lib/processor.jar CommandDispatcherMain union {input} -of {shlex.quote(dir)}/{shlex.quote(name)}.trimmed.hdr"
        await self.run(shlex.split(cmd))

    async def summarize(self, file):
        file_no_ext = os.path.splitext(file)[0]
        summary_text_name = f"{file_no_ext}-summary.txt"
        args = f"-ifp {shlex.quote(file_no_ext)}.hdr"
        await self.run(["bash", "-c", f"{self.java} -cp lib/processor.jar CommandDispatcherMain summarize {args} > {shlex.quote(summary_text_name)}"])

    async def summarize_recursively(self, dir, name):
        files = glob.iglob(f'{dir}/**/{name}.trimmed.hdr', recursive=True)
        await asyncio.gather(*(self.summarize(file) for file in files))
        return parse_profile_summary_file(f'{dir}/{name}.trimmed-summary.txt')

    async def process(self, file):
        file_no_ext = os.path.splitext(file)[0]
        tags = set()
        with open(file, "r") as hdr_file:
            reader = csv.reader(hdr_file, delimiter=',')
            # Skip headers
            for i in range(5):
                next(reader, None)
            for row in reader:
                first_column = row[0]
                tag = first_column[4:]
                tags.add(tag)

        tasks = []
        for tag in tags:
            logprocessor = f'{self.java} -cp lib/HdrHistogram-2.1.12.jar org.HdrHistogram.HistogramLogProcessor'
            args = f"-i {shlex.quote(file)} -o {shlex.quote(file_no_ext)}_{tag} -tag {tag}"
            tasks.append(self.run(shlex.split(f'{logprocessor} {args}')))
        asyncio.gather(*tasks)

    async def process_recursively(self, dir, name):
        files = glob.iglob(f'{dir}/**/{name}.trimmed.hdr', recursive=True)
        await asyncio.gather(*(self.process(file) for file in files))

ProfileSummaryResult = namedtuple('ProfileSummaryResult',
                                  ['ops_count', 'stress_time_s', 'throughput_per_second', 'mean_latency_ms',
                                   'median_latency_ms', 'p90_latency_ms', 'p99_latency_ms', 'p99_9_latency_ms',
                                   'p99_99_latency_ms', 'p99_999_latency_ms'])

def parse_profile_summary_file(path):
    with open(path) as f:
        lines = f.readlines()
        summary = dict([x.split('=') for x in lines])
        tags = set([x.split('.')[0] for x in lines])
        result = {}
        for tag in tags:
            ops_count = int(summary[f'{tag}.TotalCount'])
            stress_time_s = float(summary[f'{tag}.Period(ms)']) / 1000
            throughput_per_second = float(summary[f'{tag}.Throughput(ops/sec)'])
            mean_latency_ms = float(summary[f'{tag}.Mean']) / 1_000_000
            median_latency_ms = float(summary[f'{tag}.50.000ptile']) / 1_000_000
            p90_latency_ms = float(summary[f'{tag}.90.000ptile']) / 1_000_000
            p99_latency_ms = float(summary[f'{tag}.99.000ptile']) / 1_000_000
            p99_9_latency_ms = float(summary[f'{tag}.99.900ptile']) / 1_000_000
            p99_99_latency_ms = float(summary[f'{tag}.99.990ptile']) / 1_000_000
            p99_999_latency_ms = float(summary[f'{tag}.99.999ptile']) / 1_000_000

            result[tag] = ProfileSummaryResult(
                ops_count=ops_count,
                stress_time_s=stress_time_s,
                throughput_per_second=throughput_per_second,
                mean_latency_ms=mean_latency_ms,
                median_latency_ms=median_latency_ms,
                p90_latency_ms=p90_latency_ms,
                p99_latency_ms=p99_latency_ms,
                p99_9_latency_ms=p99_9_latency_ms,
                p99_99_latency_ms=p99_99_latency_ms,
                p99_999_latency_ms=p99_999_latency_ms)
        return result
