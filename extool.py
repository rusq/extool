#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""

    extool  Copyright (C) 2017  Rustam Gilyazov
    This program comes with ABSOLUTELY NO WARRANTY.
    This is free software, and you are welcome to redistribute it
    under certain conditions.

    extool
    ======

    Command line tool to rename Image and Video files from
    non-informative IMG_4040.JPG form to more informative,
    for example: IMG_20060302T080020_Canon-EOS10D.jpg

    It uses one of two modules (depending on their availablility):
      - exiftool_
      - pyexifinfo_

    Renames Image and Video files according to defined mask.
      - ``IMG_<YYYYMMDD>T<HH24MISS>_<Camera_model>.<ext>``
      - ``VID_<YYYYMMDD>T<HH24MISS>_<Camera_model>.<ext>``

    Where:
      - ``YYYYMMDD`` - date, i.e. 20161231
      - ``HH24MISS`` - time, i.e. 195521
      - ``Camera model`` - EXIF camera model. If not present ``noEXIF``
        value is used.
      - ``ext`` - original file extension.


    .. _exiftool: https://github.com/smarnach/pyexiftool
    .. _pyexifinfo: https://github.com/guinslym/pyexifinfo


"""
import filecmp
import glob
import logging
import os
import sys
from Queue import Queue
from threading import Lock, Thread

from dateutil import parser

try:
    import exiftool
    fast_exif = True
except ImportError:
    import pyexifinfo
    fast_exif = False

ABBREVIATIONS = {'image': 'IMG', 'video': 'VID'}
MAX_THREADS = 4


class ClosableQueue(Queue):
    SENTINEL = object()

    def close(self):
        self.put(self.SENTINEL)

    def __iter__(self):
        while True:
            item = self.get()
            try:
                if item is self.SENTINEL:
                    return
                yield item
            finally:
                self.task_done()


class Renamer(Thread):
    """Renamer thread class"""

    def __init__(self, file_queue, exception_q,
                 exiftool_handle, exiftool_lock):
        super(Renamer, self).__init__()
        self.file_queue = file_queue
        self.exiftool_handle = exiftool_handle
        self.lock = exiftool_lock
        self.exception_q = exception_q

    def get_metadata(self, filename):
        """Gets the metadata from filename, returns dict"""
        if self.exiftool_handle is not None and self.lock is not None:
            with self.lock:
                meta = self.exiftool_handle.get_metadata(filename)
                if meta.get('ExifTool:Error'):
                    pass
        else:
            try:
                meta = pyexifinfo.get_json(filename)[0]
            except ValueError:
                pass

        return meta

    def run(self):
        """Runner"""
        for filename in self.file_queue:
            try:
                self.process_file(filename)
            except Exception as e:
                self.exception_q.put(e)

    def process_file(self, filename):
        """Process a single file"""
        md = self.get_metadata(filename)
        mime = md.get('File:MIMEType', 'Unknown')
        if not (mime.startswith('image') or
                mime.startswith('video')):
            return
        if rename(filename, md):
            logger.info("Renamed: %s", filename)
        else:
            logger.error("Failed to rename %s", filename)


def slugify(string):
    """makes the camera name OS friendly

    :param str string: camera name from exif
    :return: sluggified OS friendly name
    """
    return (string
            .strip()
            .replace(' ', '-') if string else 'noEXIF')


def get_model(exif):
    """gets camera model from EXIF

    :param dict exif: EXIF data
    :return: sluggified model
    """
    ret = None
    tags = (
        'EXIF:Model',
        'QuickTime:Model'
    )
    for tag in tags:
        ret = exif.get(tag)
        if ret:
            break

    return slugify(ret)


def get_date(exif, output_fmt="%Y%m%dT%H%M%S%z"):
    """returns file date from EXIF, if not available - from filesystem data

    :param dict exif: EXIF data
    :param str output_fmt: output format

    :return: date in the specified format
    :rtype: str
    """
    ret = None
    tags = (
        'EXIF:DateTimeOriginal',
        'QuickTime:CreationDate',
        'QuickTime:MediaCreateDate',
        'File:FileModifyDate',
    )
    for tag in tags:
        dttm_str = exif.get(tag)
        if not dttm_str or dttm_str.startswith('0000'):
            continue
        # 2 possible formats:
        # 2016:12:11 13:34:33+13:00
        # 2016:11:06 02:59:05
        dttm_str = dttm_str.replace(':', '/', 2)
        try:
            dttm = parser.parse(dttm_str)
        except ValueError:
            sys.stderr.write("Failed on {0}\n".format(dttm_str))
            raise
        if not dttm:
            # unsuccessfull conversion
            raise ValueError(
                "Error converting following date: {0} in file: {1}"
                .format(dttm_str, exif.get('File:FileName')))
        ret = dttm.strftime(output_fmt)
        break
    return ret


def get_prefix(exif):
    """returns the prefix according to the file type from EXIF
    :param dict exif: EXIF data
    :return: file type prefix
    """
    ret = None
    mime = exif.get('File:MIMEType')
    ret = ABBREVIATIONS.get(mime.split('/')[0]) if mime else None
    return ret


def generate_name(exif, retry=0):
    """Generates a filename according to the mask
    :param dict exif: EXIF data

    :return: file name
    :rtype: str
    """
    ret = None
    prefix = get_prefix(exif)
    ext = exif.get('File:FileTypeExtension')
    if prefix is not None:
        date = get_date(exif)
        conflict = '' if retry == 0 else "-{}".format(retry)
        model = get_model(exif)
        live_counterpart = check_for_live(date, conflict, ext)
        if live_counterpart:
            ret = live_counterpart
        else:
            ret = ('{0}_{1}{2}_{3}.{4}'.format(
                prefix, date, conflict, model, ext))
    return ret


def check_for_live(date, conflict, ext):
    """Checks for existence of the live photo counterpart in the same dir.

    Should be called from generate_name().

    :param date: date name part
    :param conflict: conflict name part
    :param ext: extension

    :return: proper matching filename to rename to if counterpart found,
        otherwise ``None``.
    """
    # TODO Possibly support HEVC/HEIC in the future.
    if ext == 'MOV':
        # chop the time zone part
        if '+' in date:
            date = date[:date.index('+')]
        suspect_glob = ("%s_%s%s_*.%s"
                        % (ABBREVIATIONS['image'], date, conflict, 'JPG'))
        suspects = glob.glob(suspect_glob)
        if not suspects:
            return None
        if len(suspects) > 1:
            logging.warning("check_for_live: More than one match: %r",
                            suspects)
            return None
        return os.path.splitext(suspects[0])[0] + "." + ext


def rename(file_from, exif, max_rename=20):
    """ Rename the file

    :param str file_from: initial file name
    :param dict exif: EXIF data

    :return: True on success, False on failure
    :rtype: bool
    """
    retry_count = 0
    renamed = False
    this_logger = logging.getLogger(__name__)
    while not renamed:
        file_to = os.path.join(os.path.dirname(file_from),
                               generate_name(exif, retry_count))
        if os.path.exists(file_to):
            if filecmp.cmp(file_from, file_to):
                renamed = True
                this_logger.warning('File already exists: %s', file_to)
            else:
                if retry_count > max_rename:
                    break
                retry_count += 1
        else:
            try:
                os.rename(file_from, file_to)
                renamed = True
            except OSError:
                raise
    return renamed


def get_metadata(filename, exiftool_handle):
    if exiftool_handle:
        md = exiftool_handle.get_metadata(filename)
        if md.get('ExifTool:Error'):
            pass
    else:
        try:
            md = pyexifinfo.get_json(filename)[0]
        except ValueError:
            pass

    return md


def process_dir(path, exiftool_handle, exiftool_lock):
    file_queue = ClosableQueue(32)
    exception_q = Queue()

    threads = [Renamer(file_queue, exception_q,
                       exiftool_handle, exiftool_lock)
               for _ in range(0, MAX_THREADS)]

    for thread in threads:
        thread.start()

    for root, _, files in os.walk(path):
        for filename in files:
            file_queue.put(os.path.join(root, filename))

    # each thread will receive the signal.
    for _ in range(0, MAX_THREADS):
        file_queue.close()

    file_queue.join()

    if not exception_q.empty():
        sys.stderr.write("There were errors:\n")
        while not exception_q.empty():
            sys.stderr.write("%s\n" % exception_q.get(block=False).message)


if __name__ == '__main__':

    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger(__name__)

    if len(sys.argv) < 2:
        print("Usage: {0} <directory>".format(os.path.basename(sys.argv[0])))
        sys.exit(1)

    if fast_exif:
        with exiftool.ExifTool() as cm:
            exiftool_lock = Lock()
            process_dir(sys.argv[1], cm, exiftool_lock)
    else:
        process_dir(sys.argv[1], None, None)
