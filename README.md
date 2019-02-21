This is a suite of tools for processing teletext signals recorded on VHS, as
well as tools for processing teletext packet streams. The software has only
been tested with bt8x8 capture hardware, but should work with any VBI capture
hardware if you write a new configuration file (see config_bt8x8_pal.py).

This is the second rewrite of the original software. The old versions are
still available in the `v1` and `v2` branches of this repo, or from the
releases page.

You can see my collection of pages recovered with this software at:

https://al.zerostem.io/~al/teletext/

And more at:

http://www.uniquecodeanddata.co.uk/teletext76/

And:

http://archive.teletextart.co.uk/

INSTALLATION
------------

In order to use CUDA decoding you need to use the Nvidia proprietary driver.

To install with optional dependencies run:

    pip3 install .[CUDA,spellcheck,viewer]

If CUDA or pyenchant are not available for your platform simply omit them
from the install command.

In order for the output to be rendered correctly you need to use a specific
font and terminal:

    sudo apt-get install tv-fonts rxvt-unicode

Then enable bitmap fonts in your X server:

    cd /etc/fonts/conf.d
    sudo rm 70-no-bitmaps.conf
    sudo ln -s ../conf.avail/70-yes-bitmaps.conf .

After doing this you may need to reboot.

Finally open a terminal with the required font:

    urxvt -fg white -bg black -fn teletext -fb teletext -geometry 41x25 +sb &


USAGE
-----

First capture VBI from VHS:

    teletext record -d /dev/vbi0 > capture.vbi

Scan for headers in the capture:

    teletext deconvolve -H -S 20 capture.vbi > headers.txt

Examine the headers to find services on the tape:

    less -r headers.txt

Deconvolve a section of the capture corresponding to one service:

    teletext deconvolve --start <N> --stop <N> capture.vbi > stream.t42

Display all copies of a page in a stream:

    teletext filter stream.t42 -p 100

Squash duplicate subpages, which reduces errors:

    teletext filter stream.t42 --squash > output.t42

Generate HTML pages from a stream:

    mkdir output
    t42html stream.t42 output

Interactively view the pages in a t42 stream:

    cat stream.t42 | teletext interactive

In the interactive viewer you can type page numbers, or '.' for hold.

Run each command with '--help' for a complete list of options.
