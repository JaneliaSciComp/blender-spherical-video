# A script for Blender to render the frames of an animation for a
# 360-degree spherical view around a camera, using a standard map projection
# (equirectangular or Mercator).

import argparse
import bpy
import datetime
import math
import mathutils
import os
import os.path
import sys
import time

BLENDER_LEGACY_VERSION = bpy.app.version < (2, 80, 0)

# The maximum north latitude (and minimum south latitude) to be used for
# the Mercator projection (which is undefined at the poles).
MAX_LAT_MERCATOR = math.radians(85)

# The Y value that corresponds to MAX_LAT_MERCATOR.
# Computed as: math.log(math.tan(math.pi / 4 + MAX_LAT / 2))
# From: https://en.wikipedia.org/wiki/Mercator_projection
Y_FOR_MAX_LAT_MERCATOR = 3.131301331471645

# For floating-point comparisons.
EPS = 1e-10

# For efficiency.
PI_OVER_2 = math.pi / 2

def mapToLatLonMercator(x, y, width, height):
    """
    Convert from a location, `x`, `y`, in a final map image (of total size:
    `width`, `height`) to a tuple, `(latidude, longitude)`, using the
    Mercator projection.
    Latitude goes from -`MAX_LAT` at `y` == 0 to `MAX_LAT` at `y` == `height`.
    Longitude goes from -`math.pi` at `x` == 0 to `math.pi` at `x` == `width`.
    """

    # Formulas from: https://en.wikipedia.org/wiki/Mercator_projection
    # In those formulas, lambda is longitude.
    # Use radius of 1.
    lon = (2 * (x / width) - 1) * math.pi
    # “The ordinate y of the Mercator projection becomes infinite at the poles
    # and the map must be truncated at some latitude less than ninety degrees.”
    # Longitude of 85 degrees corresponds to y of 3.1.
    # MAX_LAT is a more exact calculation of this y.
    y1 = (2 * (y / height) - 1) * Y_FOR_MAX_LAT_MERCATOR
    lat =  2 * math.atan(math.exp(y1)) - PI_OVER_2
    return (lat, lon)

def mapToLatLonEquirectangular(x, y, width, height):
    """
    Convert from a location, `x`, `y`, in a final map image (of total size:
    `width`, `height`) to a tuple, `(latidude, longitude)`, using the
    equirectangular projection.
    Latitude goes from -`math.py/2` at `y` == 0 to `math.pi/2` at `y` == `height`.
    Longitude goes from -`math.pi` at `x` == 0 to `math.pi` at `x` == `width`.
    """

    # Formulas from: https://en.wikipedia.org/wiki/Equirectangular_projection
    # In those formulas, lambda is longitude.
    # Use radius of 1.
    lon = (2 * (x / width) - 1) * math.pi
    lat = (2 * (y / height) - 1) * PI_OVER_2
    return (lat, lon)

def latLonToVector(lat, lon):
    """
    Convert a latitude, `lat`, and longitude, `lon` to a 3D vector of type
    `mathutils.Vector` pointing from the center of the sphere to the point
    with that latitude and longitude.  Assumes that the "up" axis is the positive
    Z axis, as is the default for Blender.
    """

    # Use radius of 1.
    lat1 = PI_OVER_2 - lat
    s = math.sin(lat1)
    x = s * math.cos(lon)
    y = -s * math.sin(lon)
    z = math.cos(lat1)
    return mathutils.Vector((x, y, z))

def cubeIntersection(ray, prevInter=0):
    """
    Returns the intersection of `ray` with a 3D unit cube (going from -1 to 1 in
    each dimension).  The `ray` is a 3D unit vector of type `mathutils.Vector`,
    assumed to be eminating from the origin.  The result is a tuple, (`i`, `p`):
    `i` is the index of the face intersected (0 for the face at X == 1, 1 for
    X == -1, 2 for Y == 1, 3 for Y == -1, 4 for Z == 1, 5 for Z == -1), and
    `p` is the 2D intersection point on the face, of type `mathutils.Vector`,
    with each coordinate in [-1, 1].  For efficiency, `prevInter` should be
    the index of the face intersected for the preceding pixel; in many cases,
    that face will be interesected again for the current pixel, so testing it
    first allows the function to terminate more quickly.
    """

    faces = [0, 1, 2, 3, 4, 5]
    faces[0] = prevInter
    faces[prevInter] = 0
    for i in faces:
        axis = int(i / 2)
        dot = ray[axis]
        if i % 2 == 1:
            dot = -dot

        # If dot is negative, then ray is pointing away from this face,
        # and only the flipped ray would interset the face.
        # If dot is essentially 0 (less than EPS) then the ray is parallel
        # to the face and would never intersect it.
        if dot < EPS:
            continue

        pt = []
        for j in [k for k in range(3) if k != axis]:
            inter = ray[j] / dot
            if abs(inter) <= 1:
                pt.append(inter)
            else:
                break
        if len(pt) == 2:
            return (i, mathutils.Vector(pt))

    # Should never happen.
    return None

class Sizes:
    """
    A convenient collection of the sizes used in the conversion from six images
    on the face of a cube to the final spherical image.
    `width` and `height` are the dimension, in pixels, of the final image.
    `cube` is width and height of each cube image.
    `subWidth` and `subHeight` give the number of subsamples used to compute
    each pixel in the final image.
    """
    def __init__(self, width, height, cubeSize, subWidth, subHeight):
        self.width = width
        self.height = height
        self.cube = cubeSize
        self.subWidth = subWidth
        self.subHeight = subHeight

def createSamplingIndices(sizes, mapToLatLon=mapToLatLonEquirectangular, cache=True):
    """
    Returns the indices used to resample the rendered cube images into the final
    spherical image.  The indices consist of a list with one element per final
    image pixel.  That element is itself a list of tuples, one for each of the
    subsamples used to compute the pixel.  Each tuple has the form `(i, x, y)`,
    as returned by `cubeIntersection`: `i` is the index of a face image, and
    `x` and `y` are a point on that image from which to sample. The `mapToLatLon`
    function is used to compute latitudes and longitudes, and is an argument so
    different projections (e.g., equirectangular, Mercator) can be supported.
    Note that the indices depend only on the various image dimensions in `sizes`
    and do not depend on the actual cube images.  Thus, the indices can be
    computed once at the beginning of the rendering of an animation, and reused
    at each frame.  In fact, the indices are cached and reused across animations,
    unless the `cache` argument is `False`.
    """
    projectionTag = getProjectionTag(mapToLatLon)
    if cache:
        cachedResult = readSamplingIndicesFromCache(sizes, projectionTag)
        if cachedResult != None:
            print("Using cached sampling indices")
            return cachedResult
    else:
        print("Ignoring the samping indices cache")

    result = []
    xSubDx = 1 / (sizes.subWidth + 1)
    ySubDy = 1 / (sizes.subHeight + 1)

    # Initialize inter as if there was as previous call to cubeIntersection()
    # that intersected face 0.  That way, all faces will be considered.
    inter = [0]

    # The X computed by cubeIntersection could be either left or right in the
    # cube face image to be sampled.  This factor gives it the correct orientation
    # for the face that was intersected.
    orientation = [-1, 1, 1, -1, -1, 1]

    # Local variables for functions improve peformance, according to timing tests.
    # See https://wiki.python.org/moin/PythonSpeed/PerformanceTips
    append = list.append
    # But using local variables for the instance attributes of "sizes" did not
    # give much improvement.

    nSub = sizes.subWidth * sizes.subHeight
    for y in range(sizes.height):
        for x in range(sizes.width):
            append(result, [])
            ySub = y + ySubDy
            for _ in range(sizes.subHeight):
                xSub = x + xSubDx
                for _ in range(sizes.subWidth):
                    latLon = mapToLatLon(xSub, ySub, sizes.width, sizes.height)
                    ray = latLonToVector(latLon[0], latLon[1])
                    inter = cubeIntersection(ray, inter[0])

                    face = inter[0]
                    xInter = inter[1][0] * orientation[face]
                    yInter = inter[1][1]

                    xFace = int(sizes.cube * ((xInter + 1) / 2))
                    yFace = int(sizes.cube * ((yInter + 1) / 2))
                    append(result[-1], (face, xFace, yFace))
                    xSub += xSubDx
                ySub += ySubDy

    if cache:
        writeSamplingIndicesToCache(sizes, projectionTag, result)

    return result

def toBinary(samplingIndices):
    """
    Converts the structure returned by `createSamplingIndices` into a binary
    form, appropriate for storing in a cache file.
    """

    # Local variables for functions improve peformance, according to timing tests.
    # See https://wiki.python.org/moin/PythonSpeed/PerformanceTips
    toBytes = int.to_bytes

    ba = bytearray()
    for pixel in samplingIndices:
        for sample in pixel:
            ba += toBytes(sample[0], 1, "big")
            ba += toBytes(sample[1], 2, "big")
            ba += toBytes(sample[2], 2, "big")
    return ba

def fromBinary(sizes, ba):
    """
    Converts `ba`, the binary form returned by `toBinary`, back into a structure
    like that returned by `createSamplingIndices`.
    """

    samplingIndices = []
    IntsPerSample = 3
    samplesPerPixel = sizes.subWidth * sizes.subHeight
    intsPerPixel = IntsPerSample * samplesPerPixel
    nInts = sizes.width * sizes.height * intsPerPixel
    iBa = 0

    # Local variables for functions improve peformance, according to timing tests.
    # See https://wiki.python.org/moin/PythonSpeed/PerformanceTips
    fromBytes = int.from_bytes
    append = list.append

    for i in range(0, nInts, IntsPerSample):
        if i % intsPerPixel == 0:
            append(samplingIndices, [])

        # Unwinding the loop over the integers in one sample's tuple gives a
        # significant improvement in performance, according to timing tests.
        face = fromBytes(ba[iBa:iBa+1], "big")
        xFace = fromBytes(ba[iBa+1:iBa+3], "big")
        yFace = fromBytes(ba[iBa+3:iBa+5], "big")
        iBa += 5
        sample = (face, xFace, yFace)

        append(samplingIndices[-1], sample)
    return samplingIndices

def cacheFilePath(sizes, projectionTag):
    """
    Returns the path to a cache file for the sampling indices built with the
    image dimensions in `sizes` and the projection type indicated by
    `projectionTag`.  Creates the directory for cache files if it does
    not exist already.
    """

    path = os.path.dirname(os.path.realpath(__file__))
    path = os.path.join(path, "samplingIndexCache")
    if not os.path.exists(path):
        os.mkdir(path)
    file = "samplingIndices_w{}_h{}_cu{}_sw{}_sh{}_{}".\
        format(sizes.width, sizes.height, sizes.cube, sizes.subWidth, sizes.subHeight, projectionTag)
    return os.path.join(path, file)

def writeSamplingIndicesToCache(sizes, projectionTag, samplingIndices):
    """
    Converts `samplingIndices` to binary and writes it to a cache file.  The
    image dimensions from `sizes` and the projection type indicated by
    `projectionTag` are used in the name of the cache file.
    """

    try:
        path = cacheFilePath(sizes, projectionTag)
        ba = toBinary(samplingIndices)
        with open(path, "wb") as f:
            f.write(ba)
    except Exception as e:
        print("Warning: cannot write sampling indices cache: '{}'".format(str(e)))


def readSamplingIndicesFromCache(sizes, projectionTag):
    """
    Returns the sampling indices read from a cache file indentified by the image
    dimensions from `sizes` and the projection type indicated by `projectionTag`.
    The cache file must also have a modification time later than this source file.
    If no matching cache exists, returns `None`.
    """

    try:
        path = cacheFilePath(sizes, projectionTag)
        if os.path.exists(path):
            with open(path, "rb") as f:
                creationTime = os.path.getmtime(path)
                codeModificationTime = os.path.getmtime(__file__)
                if creationTime > codeModificationTime:
                    print("Reading sampling indices cache '{}'...".format(path))
                    t0 = time.time()
                    ba = bytearray(f.read())
                    t1 = time.time()
                    print("Done, {:.2f} secs".format(t1 - t0))
                    print("Applying cache...")
                    t0 = time.time()
                    result = fromBinary(sizes, ba)
                    t1 = time.time()
                    print("Done, {:.2f} secs".format(t1 - t0))
                    return result
    except Exception as e:
        print("Warning: cannot read sampling indices cache: '{}'".format(str(e)))
    return None

def getProjectionTag(mapToLatLon):
    """
    Returns a string indicating the type of projection used in `mapToLatLon`.
    This string is used to tag a cache file.
    """

    if mapToLatLon == mapToLatLonEquirectangular:
        return "eqrc"
    elif mapToLatLon == mapToLatLonMercator:
        return "merc"
    else:
        return "unkn"

def getCubePixels(cubeImages):
    """
    Returns a list containing the raw pixels from the `bpy.types.Image` images
    in the list `cubeImages`.  Factoring this functionality out into its own
    function is useful for performance profiling.
    """

    return [face.pixels[:] for face in cubeImages]

def makeEmpty(name, scene):
    """
    Returns a new empty node, linked into `scene`.
    """
    empty = bpy.data.objects.new(name, None)
    if BLENDER_LEGACY_VERSION:
        scene.object.link(empty)
    else:
        scene.collection.objects.link(empty)
    return empty

def makeCamera(name, scene):
    """
    Retruns a new camera, appropriate for rendering a cube face, linked into
    `scene`.
    """
    cameraData = bpy.data.cameras.new(name)
    cameraData.lens_unit = "FOV"
    cameraData.angle = PI_OVER_2
    camera = bpy.data.objects.new(name, cameraData)
    if BLENDER_LEGACY_VERSION:
        scene.object.link(camera)
    else:
        scene.collection.objects.link(camera)
    return camera

def makeImage(name, sizes, pixels):
    """
    Returns a new `bpy.types.Image` with the specified `name` and `pixels`,
    and having dimensions `sizes.width` and `sizes.height`.  Factoring this
    functionality out into its own function is useful for performance profiling.
    """

    result = bpy.data.images.new(name, width=sizes.width, height=sizes.height)
    result.pixels = pixels
    return result

def createImageFromSamplingIndices(samplingIndices, sizes, cubeImages):
    """
    Returns the final spherical image by resampling the `cubeImages` according
    to the `samplingIndices`.  The width and height of the final image are
    specified by `sizes`.
    """

    ChannelsPerPixel = 4
    cubePixels = getCubePixels(cubeImages)
    cubeSize = sizes.cube
    resultPixels = [0, 0, 0, 1] * sizes.width * sizes.height
    iResult = 0
    for pixelIndex in samplingIndices:
        pixel = [0, 0, 0, 1]
        for subIndex in pixelIndex:
            facePixels = cubePixels[subIndex[0]]
            xFace = subIndex[1]
            yFace = subIndex[2]
            iSub = (yFace * cubeSize + xFace) * ChannelsPerPixel
            for l in range(ChannelsPerPixel):
                pixel[l] += facePixels[iSub + l]
        pixel = [x / len(pixelIndex) for x in pixel]
        for l in range(ChannelsPerPixel):
            resultPixels[iResult + l] = pixel[l]
        iResult += ChannelsPerPixel
    return makeImage("createImageFromSamplingIndices", sizes, resultPixels)

def render(cameraName, outputBasePath, sizes, start=1, end=250, step=1, mercator=False, cache=True):
    """
    Renders an animation of the spherical image around the camera named
    `cameraName`.  The spherical image is built by resampling images on the
    faces of a cube around the camera.  The final spherical image frames are
    stored in the "spherical" subdirectory of the base directory specified by
    `outputBasePath`.  The intermedial cube image frames are stored in other
    subdirectories of `outputBasePath`.  The dimensions of the intermediate and
    final images are specified by `sizes`.  The frames included in the animation
    are specified by `start`, `end` and `step`.
    """

    cam = bpy.data.objects[cameraName]

    scene = bpy.context.scene
    scene.render.resolution_x = sizes.cube
    scene.render.resolution_y = sizes.cube
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"

    # For each side of the cube, the name of subdirectory of `outputBasePath`
    # where the rendered frames are stored, and the Euler angles to orient the
    # camera when rendering that side of the cube.
    views = [
        { "subdir" : "xPos", "rot" : (0,         0,         0) },
        { "subdir" : "xNeg", "rot" : (math.pi,   0,         math.pi) },
        { "subdir" : "yPos", "rot" : (0,         PI_OVER_2, 0) },
        { "subdir" : "yNeg", "rot" : (0,        -PI_OVER_2, 0) },
        { "subdir" : "zPos", "rot" : (0,        -PI_OVER_2, PI_OVER_2) },
        { "subdir" : "zNeg", "rot" : (0,         PI_OVER_2, PI_OVER_2) }
    ]

    cubeCams = []
    # This node is the parent of all the cube-face cameras, in case there is a
    # need for reorienting all of them in unison.
    cubeCamsParent = makeEmpty("CubeCameras", scene)
    cubeCamsParent.parent = cam
    for view in views:
        cam = makeCamera(view["subdir"], scene)
        cam.parent = cubeCamsParent
        cam.rotation_euler = view["rot"]
        cubeCams.append(cam)

    if __name__ == "__main__":
        t0 = time.time()
        print("Building sampling indices...")

    mappingFunc = mapToLatLonMercator if mercator else mapToLatLonEquirectangular
    samplingIndices = createSamplingIndices(sizes, mappingFunc, cache)

    if __name__ == "__main__":
        t1 = time.time()
        print("Done, {:.2f} secs".format(t1 - t0))

    if not os.path.exists(outputBasePath):
        os.mkdir(outputBasePath)
    outputSphericalPath = os.path.join(outputBasePath, "spherical/")
    if not os.path.exists(outputSphericalPath):
        os.mkdir(outputSphericalPath)

    frame = start
    while frame <= end:
        scene.frame_set(frame)
        frameStr = str(frame).zfill(4) + ".png"
        cubeImages = []

        for cubeCam in cubeCams:
            scene.camera = cubeCam
            scene.render.filepath = os.path.join(outputBasePath, cubeCam.name, frameStr)
            bpy.ops.render.render(write_still=True)
            cubeImages.append(bpy.data.images.load(scene.render.filepath))

        if __name__ == "__main__":
            t0 = time.time()
            print("Resampling spherical image...")

        image = createImageFromSamplingIndices(samplingIndices, sizes, cubeImages)

        image.filepath_raw = os.path.join(outputSphericalPath, frameStr)
        image.file_format = "PNG"
        image.save()

        if __name__ == "__main__":
            t1 = time.time()
            print("Done, {:.2f} secs".format(t1 - t0))
            print("Saved '{}'".format(image.filepath_raw))
            print("")

        frame += step

if __name__ == "__main__":
    timeStart = datetime.datetime.now()
    argv = sys.argv
    if "--" not in argv:
        argv = []
    else:
        argv = argv[argv.index("--") + 1:]

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", dest="inputBlenderFile", help="path to the input .blend file")
    parser.set_defaults(cameraName="Camera")
    parser.add_argument("--camera", "-c", dest="cameraName", help="camera name from .blend file")
    parser.set_defaults(outputBasePath="./spherical-video")
    parser.add_argument("--output", "-o", dest="outputBasePath", help="path to output directory")
    parser.set_defaults(width=1280)
    parser.add_argument("--width", "-ow", type=int, dest="width", help="width of output spherical image")
    parser.set_defaults(height=720)
    parser.add_argument("--height", "-oh", type=int, dest="height", help="height of output spherical image")
    parser.add_argument("--cubeSize", "-cu", type=int, dest="cubeSize", help="width (height) of cube faces")
    parser.set_defaults(subWidth=3)
    parser.add_argument("--subWidth", "-sw", type=int, dest="subWidth", help="number of subsamples for width")
    parser.set_defaults(subHeight=3)
    parser.add_argument("--subHeight", "-sh", type=int, dest="subHeight", help="number of subsamples for height")
    parser.add_argument("--frame-start", "-s", type=int, dest="start", help="first frame to render")
    parser.add_argument("--frame-end", "-e", type=int, dest="end", help="last frame to render")
    parser.add_argument("--frame-jump", "-j", type=int, dest="step", help="number of frames to step forward")
    parser.set_defaults(projectionType=0)
    parser.add_argument("--proj", "-pr", type=int, dest="projectionType", help="projection type (0: equirectangular, 1: Mercator)")
    parser.set_defaults(cache=True)
    parser.add_argument("--nocache", "-nc", dest="cache", action="store_false", help="do NOT use caching")
    args = parser.parse_args(argv)

    bpy.ops.wm.open_mainfile(filepath=args.inputBlenderFile)

    cubeSize = max(int(args.width * 0.75), int(args.height * 0.75))
    if args.cubeSize != None:
        cubeSize = args.cubeSize
    mercator = (args.projectionType == 1)

    sizes = Sizes(args.width, args.height, cubeSize, args.subWidth, args.subHeight)

    start = bpy.context.scene.frame_start
    if args.start != None:
        start = args.start
    end = bpy.context.scene.frame_end
    if args.end != None:
        end = args.end
    step = bpy.context.scene.frame_step
    if args.step != None:
        step = args.step

    render(args.cameraName, args.outputBasePath, sizes, start, end, step, mercator, args.cache)

    timeEnd = datetime.datetime.now()
    print("Rendering started at {}".format(timeStart))
    print("Rendering ended at {}".format(timeEnd))
