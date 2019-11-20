import cProfile
import os
import stat
from functools import wraps

import click
from tqdm import tqdm

from . import pipeline
from .packet import Packet
from .stats import StatsList, MagHistogram, RowHistogram, ErrorHistogram
from .file import FileChunker
from .vbi.config import Config

try:
    import plop.collector as plop
except ImportError:
    plop = None


def filterparams(f):
    for d in [
        click.option('-m', '--mag', 'mags', type=int, multiple=True, default=range(9), help='Limit output to specific magazines. Can be specified multiple times.'),
        click.option('-r', '--row', 'rows', type=int, multiple=True, default=range(32), help='Limit output to specific rows. Can be specified multiple times.'),
    ][::-1]:
        f = d(f)
    return f


def progressparams(progress=None, mag_hist=None, row_hist=None, err_hist=None):

    def p(f):
        for d in [
            click.option('--progress/--no-progress', default=progress, help='Display progress bar.'),
            click.option('--mag-hist/--no-mag-hist', default=mag_hist, help='Display magazine histogram.'),
            click.option('--row-hist/--no-row-hist', default=row_hist, help='Display row histogram.'),
            click.option('--err-hist/--no-err-hist', default=err_hist, help='Display error distribution.'),
        ][::-1]:
            f = d(f)
        return f
    return p


def carduser(extended=False):
    def c(f):
        if extended:
            for d in [
                click.option('--sample-rate', type=float, default=None, help='Override capture card sample rate (Hz).'),
                click.option('--line-start-range', type=(int, int), default=(None, None), help='Override capture card line start offset.'),
            ][::-1]:
                f = d(f)

        @click.option('-c', '--card', type=click.Choice(list(Config.cards.keys())), default='bt8x8', help='Capture device type. Default: bt8x8.')
        @click.option('--line-length', type=int, default=None, help='Override capture card samples per line.')
        @wraps(f)
        def wrapper(card, line_length=None, sample_rate=None, line_start_range=None, *args, **kwargs):
            if line_start_range == (None, None):
                line_start_range = None
            config = Config(card=card, line_length=line_length, sample_rate=sample_rate, line_start_range=line_start_range)
            return f(config=config, *args,**kwargs)
        return wrapper
    return c


def chunkreader(f):
    @click.argument('input', type=click.File('rb'), default='-')
    @click.option('--start', type=int, default=0, help='Start at the Nth line of the input file.')
    @click.option('--stop', type=int, default=None, help='Stop before the Nth line of the input file.')
    @click.option('--step', type=int, default=1, help='Process every Nth line from the input file.')
    @click.option('--limit', type=int, default=None, help='Stop after processing N lines from the input file.')
    @wraps(f)
    def wrapper(input, start, stop, step, limit, *args, **kwargs):

        if input.isatty():
            raise click.UsageError('No input file and stdin is a tty - exiting.', )

        if 'progress' in kwargs and kwargs['progress'] is None:
            if hasattr(input, 'fileno') and stat.S_ISFIFO(os.fstat(input.fileno()).st_mode):
                kwargs['progress'] = False

        chunker = lambda size, flines=16, frange=range(0, 16): FileChunker(input, size, start, stop, step, limit, flines, frange)

        return f(chunker=chunker, *args, **kwargs)
    return wrapper


def packetreader(f):
    @chunkreader
    @click.option('--wst', is_flag=True, default=False, help='Input is 43 bytes per packet (WST capture card format.)')
    @filterparams
    @progressparams()
    @wraps(f)
    def wrapper(chunker, wst, mags, rows, progress, mag_hist, row_hist, err_hist, *args, **kwargs):

        if wst:
            chunks = chunker(43)
            chunks = ((c[0],c[1][:42]) for c in chunks if c[1][0] != 0)
        else:
            chunks = chunker(42)

        if progress is None:
            progress = True

        if progress:
            chunks = tqdm(chunks, unit='P', dynamic_ncols=True)
            if any((mag_hist, row_hist)):
                chunks.postfix = StatsList()

        packets = (Packet(data, number) for number, data in chunks)
        packets = (p for p in packets if p.mrag.magazine in mags and p.mrag.row in rows)

        if progress and mag_hist:
            packets = MagHistogram(packets)
            chunks.postfix.append(packets)
        if progress and row_hist:
            packets = RowHistogram(packets)
            chunks.postfix.append(packets)
        if progress and err_hist:
            packets = ErrorHistogram(packets)
            chunks.postfix.append(packets)

        return f(packets=packets, *args, **kwargs)

    return wrapper


def paginated(always=False, filtered=True):
    def _paginated(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            paginate = always or kwargs['paginate']

            if filtered:
                pages = kwargs['pages']
                if pages is None or len(pages) == 0:
                    pages = range(0x900)
                else:
                    pages = {int(x, 16) for x in pages}
                    paginate = True
                kwargs['pages'] = pages

                subpages = kwargs['subpages']
                if subpages is None or len(subpages) == 0:
                    subpages = range(0x3f80)
                else:
                    subpages = {int(x, 16) for x in subpages}
                    paginate = True
                kwargs['subpages'] = subpages

            if paginate and 0 not in kwargs['rows']:
                raise click.BadArgumentUsage("Can't paginate when row 0 is filtered.")

            if not always:
                kwargs['paginate'] = paginate

            return f(*args, **kwargs)

        if filtered:
            wrapper = click.option('-s', '--subpage', 'subpages', type=str, multiple=True,
                      help='Limit output to specific subpage. Can be specified multiple times.')(wrapper)
            wrapper = click.option('-p', '--page', 'pages', type=str, multiple=True,
                      help='Limit output to specific page. Can be specified multiple times.')(wrapper)
        if not always:
            wrapper = click.option('-P', '--paginate', is_flag=True, help='Sort rows into contiguous pages.')(wrapper)

        return wrapper
    return _paginated


def packetwriter(f):
    @click.option(
        '-o', '--output', type=(click.Choice(['auto', 'text', 'ansi', 'debug', 'bar', 'bytes', 'vbi']), click.File('wb')),
        multiple=True, default=[('auto', '-')]
    )
    @wraps(f)
    def wrapper(output, *args, **kwargs):

        if 'progress' in kwargs and kwargs['progress'] is None:
            for attr, o in output:
                if o.isatty():
                    kwargs['progress'] = False

        packets = f(*args, **kwargs)

        for attr, o in output:
            packets = pipeline.to_file(packets, o, attr)

        for p in packets:
            pass

    return wrapper


def profileopts(f):
    if plop is not None:
        @click.option('--profile', type=str, default=None)
        @click.pass_context
        @wraps(f)
        def group(ctx, profile, *args, **kwargs):
            ctx.ensure_object(dict)
            ctx.obj['PROFILE'] = profile
            return f(*args, **kwargs)
        return group
    else:
        return f


def command(group, *args, **kwargs):
    def deco(f):
        @group.command(*args, **kwargs)
        @click.pass_context
        @wraps(f)
        def cmd(ctx, *_args, **_kwargs):
            tqdm.monitor_interval = 0

            if plop is not None and ctx.obj['PROFILE'] is not None:
                # disable tqdm monitor thread as it messes with the profiling

                p = plop.Collector()
                p.start()
                try:
                    return f(*_args, **_kwargs)
                finally:
                    p.stop()
                    plop.FlamegraphFormatter().store(p, ctx.obj['PROFILE'])
            else:
                return f(*_args, **_kwargs)
        return cmd
    return deco
