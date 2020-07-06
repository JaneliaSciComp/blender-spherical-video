# Utilities related to image file formats supported by Blender.

import functools

fileFormatToExt = {
    "BMP": ".bmp",
    "IRIS": ".sgi",
    "PNG": ".png",
    "JPEG": ".jpg",
    "JPEG2000": ".jp2",
    "TARGA": ".tga",
    "CINEON": ".cin",
    "DPX": ".dpx",
    "OPEN_EXR": ".exr",
    "HDR": ".hdr",
    "TIFF": ".tif"
}

def unknownFormatErrorMessage(format):
    result = "Unsupported file format '{}'; use one of: ".format(format)
    l = list(fileFormatToExt.items())
    result = functools.reduce(lambda a, b: a + "{} ({}), ".format(b[0], b[1]), l, result)[:-2]
    return result
