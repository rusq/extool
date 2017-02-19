#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import filecmp
import logging
import exiftool
from dateutil import parser


def slugify(string):
    return string.strip().replace(' ', '-') if string is not None else 'noEXIF'


def get_model(exif):
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
    ret = None
    tags = (
        'EXIF:DateTimeOriginal',
        'QuickTime:CreationDate',
        'File:FileModifyDate',
    )
    for tag in tags:
        dttm_str = exif.get(tag)
        if not dttm_str:
            continue
        # 2 possible formats:
        # 2016:12:11 13:34:33+13:00
        # 2016:11:06 02:59:05
        # dttm_str = dttm_str.replace(':', '')
        dttm = parser.parse(dttm_str)
        if dttm is None:
            # unsuccessfull conversion
            raise ValueError(
                "Error converting following date: {0} in file: {1}"
                .format(dttm_str, exif.get('File:FileName')))
        ret = dttm.strftime(output_fmt)
        break
    return ret


def get_prefix(exif):
    ret = None
    abbreviations = {'image': 'IMG', 'video': 'VID'}
    mime = exif.get('File:MIMEType')
    ret = abbreviations.get(mime.split('/')[0]) if mime is not None else None
    return ret


def generate_name(exif, retry=0):
    ret = None
    prefix = get_prefix(exif)
    ext = exif.get('File:FileTypeExtension')
    if prefix is not None:
        ret = ('{}_{}{}_{}.{}'
               .format(prefix,
                       get_date(exif),
                       '' if retry == 0 else "-{}".format(retry),
                       get_model(exif),
                       ext)
               )
    return ret


def rename(file_from, exif):
    MAX_RENAME = 20
    retry_count = 0
    renamed = False
    logger = logging.getLogger(__name__)
    while not renamed:
        file_to = os.path.join(os.path.dirname(file_from),
                               generate_name(exif, retry_count))
        if os.path.exists(file_to):
            if filecmp.cmp(file_from, file_to):
                renamed = True
                logger.warning('File already exists: {}'.format(file_to))
            else:
                if retry_count > MAX_RENAME:
                    break
                retry_count += 1
        else:
            try:
                os.rename(file_from, file_to)
                renamed = True
            except:
                raise
    return renamed


if __name__ == '__main__':
    # et = exiftool.ExifTool()
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger(__name__)

#    logger.setLevel(20)

    if len(sys.argv) < 2:
        print("Usage: {} <directory>".format(os.path.basename(sys.argv[0])))
        sys.exit(1)

    files_list = list()
    for root, subdirs, files in os.walk(sys.argv[1]):
        for file in files:
            files_list.append(os.path.join(root, file))

    with exiftool.ExifTool() as et:
        for file in files_list:
            md = et.get_metadata(file)
            if md.get('ExifTool:Error') is not None:
                continue
            if (not md.get('File:MIMEType', 'Unknown').startswith('image') and
                    not (md
                         .get('File:MIMEType', 'Unknown')
                         .startswith('video'))):
                continue
            if rename(file, md):
                logger.info("Renamed: {}".format(file))
            else:
                logger.error("Failed to rename {}".format(file))
