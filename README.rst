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


