# Tests for sphericalVideo.py
# Run in Blender:
# blender --background --python test_sphericalVideo.py

import argparse
import bpy
import filecmp
import math
from math import pi
from math import sqrt
from mathutils import Vector
import os
import sys
import unittest

# Since Blender includes its own installation of Python, and proper uses of
# virtual environments are complicated, this approach to making sphericalVideo.py
# accessable seems acceptable.
sys.path.append(os.path.dirname(os.path.realpath(__file__)))

from sphericalVideo import mapToLatLonMercator, MAX_LAT_MERCATOR, \
                           mapToLatLonEquirectangular, \
                           latLonToVector, cubeIntersection, \
                           Sizes, \
                           createSamplingIndices, createImageFromSamplingIndices, \
                           toBinary, fromBinary

argv = sys.argv
if "--" not in argv:
    argv = []
else:
    argv = argv[argv.index("--") + 1:]

parser = argparse.ArgumentParser()
args = parser.parse_args(argv)

class VectorsAlmostEqual:
    def assertVectorsAlmostEqual(self, v1, v2, places=7):
        eps = math.pow(10, -places)
        diff = (v1 - v2).magnitude
        if diff > eps:
            raise AssertionError("Vectors differ: {} != {} by {}, more than {}".format(v1, v2, eps, diff))

class TestSphericalVideo(unittest.TestCase, VectorsAlmostEqual):

    def test_mapToLatLonMercator(self):
        w = 20
        h = 10

        self.assertEqual(mapToLatLonMercator(x=w/2, y=h/2, width=w, height=h), (0, 0))

        self.assertEqual(mapToLatLonMercator(x=0, y=h/2, width=w, height=h), (0, -pi))
        self.assertEqual(mapToLatLonMercator(x=w, y=h/2, width=w, height=h), (0,  pi))

        self.assertEqual(mapToLatLonMercator(x=w/2, y=0, width=w, height=h), (-MAX_LAT_MERCATOR, 0))
        self.assertEqual(mapToLatLonMercator(x=w/2, y=h, width=w, height=h), ( MAX_LAT_MERCATOR, 0))

    def test_mapToLatLonEquirectangular(self):
        w = 20
        h = 10

        self.assertEqual(mapToLatLonEquirectangular(x=w/2, y=h/2, width=w, height=h), (0, 0))

        self.assertEqual(mapToLatLonEquirectangular(x=0, y=h/2, width=w, height=h), (0, -pi))
        self.assertEqual(mapToLatLonEquirectangular(x=w, y=h/2, width=w, height=h), (0,  pi))

        self.assertEqual(mapToLatLonEquirectangular(x=w/2, y=0, width=w, height=h), (-pi / 2, 0))
        self.assertEqual(mapToLatLonEquirectangular(x=w/2, y=h, width=w, height=h), ( pi / 2, 0))

    def test_latLonToVector(self):
        self.assertVectorsAlmostEqual(latLonToVector(0, 0), Vector((1, 0, 0)))

        self.assertVectorsAlmostEqual(latLonToVector( pi/4, 0), Vector((sqrt(2)/2, 0,  sqrt(2)/2)))
        self.assertVectorsAlmostEqual(latLonToVector(-pi/4, 0), Vector((sqrt(2)/2, 0, -sqrt(2)/2)))

        self.assertVectorsAlmostEqual(latLonToVector(0,  pi/4), Vector((sqrt(2)/2, -sqrt(2)/2, 0)))
        self.assertVectorsAlmostEqual(latLonToVector(0, -pi/4), Vector((sqrt(2)/2,  sqrt(2)/2, 0)))

    def test_cubeIntersection(self):
        tests = [
            { "face" : 0, "pt" : Vector(( 1.0,  0.1,  0.2)) },
            { "face" : 0, "pt" : Vector(( 1.0, -0.2,  0.3)) },
            { "face" : 0, "pt" : Vector(( 1.0, -0.3, -0.4)) },
            { "face" : 0, "pt" : Vector(( 1.0,  0.4, -0.5)) },
            { "face" : 1, "pt" : Vector((-1.0,  0.1,  0.2)) },
            { "face" : 1, "pt" : Vector((-1.0, -0.2,  0.3)) },
            { "face" : 1, "pt" : Vector((-1.0, -0.3, -0.4)) },
            { "face" : 1, "pt" : Vector((-1.0,  0.4, -0.5)) },
            { "face" : 2, "pt" : Vector(( 0.1,  1.0,  0.2)) },
            { "face" : 2, "pt" : Vector((-0.2,  1.0,  0.3)) },
            { "face" : 2, "pt" : Vector((-0.3,  1.0, -0.4)) },
            { "face" : 2, "pt" : Vector(( 0.4,  1.0, -0.5)) },
            { "face" : 3, "pt" : Vector(( 0.1, -1.0,  0.2)) },
            { "face" : 3, "pt" : Vector((-0.2, -1.0,  0.3)) },
            { "face" : 3, "pt" : Vector((-0.3, -1.0, -0.4)) },
            { "face" : 3, "pt" : Vector(( 0.4, -1.0, -0.5)) },
            { "face" : 4, "pt" : Vector(( 0.1,  0.2,  1.0)) },
            { "face" : 4, "pt" : Vector((-0.2,  0.3,  1.0)) },
            { "face" : 4, "pt" : Vector((-0.3, -0.4,  1.0)) },
            { "face" : 4, "pt" : Vector(( 0.4, -0.5,  1.0)) },
            { "face" : 5, "pt" : Vector(( 0.1,  0.2, -1.0)) },
            { "face" : 5, "pt" : Vector((-0.2,  0.3, -1.0)) },
            { "face" : 5, "pt" : Vector((-0.3, -0.4, -1.0)) },
            { "face" : 5, "pt" : Vector(( 0.4, -0.5, -1.0)) }
        ]

        for test in tests:
            # A ray from the origin to a point on a cube face is just that point normalized.
            ray = test["pt"].normalized()
            # The expected intersection point is that point converted to 2D by dropping
            # the coordinate of the face, that is, the coordinate for which the face normal is 1.
            faceNormalCoord = int(test["face"] / 2)
            expectedPt2D = Vector([test["pt"][i] for i in range(3) if i != faceNormalCoord])

            result = cubeIntersection(ray)
            self.assertEqual(result[0], test["face"])
            self.assertVectorsAlmostEqual(result[1], expectedPt2D)

    def test_byteArray(self):
        sizes = Sizes(width=3, height=2, cubeSize=10, subWidth=3, subHeight=3)
        samplingIndices1 = [
            [(0,0,0), (0,0,1), (0,0,2), (0,1,0), (0,1,1), (0,1,2), (0,2,0), (0,2,1), (0,2,2)],
            [(1,0,0), (1,0,1), (1,0,2), (1,1,0), (1,1,1), (1,1,2), (1,2,0), (1,2,1), (1,2,2)],
            [(2,0,0), (2,0,1), (2,0,2), (2,1,0), (2,1,1), (2,1,2), (2,2,0), (2,2,1), (2,2,2)],
            [(3,0,0), (3,0,1), (3,0,2), (3,1,0), (3,1,1), (3,1,2), (3,2,0), (3,2,1), (3,2,2)],
            [(4,0,0), (4,0,1), (4,0,2), (4,1,0), (4,1,1), (4,1,2), (4,2,0), (4,2,1), (4,2,2)],
            [(5,0,0), (5,0,1), (5,0,2), (5,1,0), (5,1,1), (5,1,2), (5,2,0), (5,2,1), (5,2,2)]
        ]
        ba = toBinary(samplingIndices1)
        samplingIndices2 = fromBinary(sizes, ba)
        self.assertEqual(samplingIndices1, samplingIndices2)

    def createImage(self, width, height, color1, color2):
        image = bpy.data.images.new("test", width=width, height=height)
        pixels = []
        if True:
            for i in range(height):
                pixels += color1 * i + color2 * (width - i)
        elif False:
            for i in range(height):
                if i < height / 2:
                    pixels += color1 * i + color2 * (width - i)
                else:
                    pixels += color1 * width
        else:
            for i in range(height):
                pixels += color1 * int(width / 2) + color2 * int(width / 2)

        image.pixels = pixels.copy()
        return image

    def test_createImage(self):
        sizes = Sizes(width=int(1280/4), height=int(720/4), cubeSize=500, subWidth=3, subHeight=3)

        cubeImages = [self.createImage(sizes.cube, sizes.cube, [1, 0, 0, 1], [1,   0.5, 0.5, 1]),
                      self.createImage(sizes.cube, sizes.cube, [0, 1, 1, 1], [0.5, 1,   1,   1]),
                      self.createImage(sizes.cube, sizes.cube, [0, 1, 0, 1], [0.5, 1,   0.5, 1]),
                      self.createImage(sizes.cube, sizes.cube, [1, 0, 1, 1], [1,   0.5, 1,   1]),
                      self.createImage(sizes.cube, sizes.cube, [0, 0, 1, 1], [0.5, 0.5, 1,   1]),
                      self.createImage(sizes.cube, sizes.cube, [1, 1, 0, 1], [1,   1,   0.5, 1])]

        samplingIndices = createSamplingIndices(sizes, mapToLatLon=mapToLatLonEquirectangular)
        image = createImageFromSamplingIndices(samplingIndices, sizes, cubeImages)

        dir = os.path.dirname(os.path.realpath(__file__))

        image.filepath_raw = os.path.join(dir, "test_createImage.png")
        image.file_format = "PNG"
        image.save()

        expected = os.path.join(dir, "test_createImage_expected.png")
        self.assertTrue(filecmp.cmp(image.filepath_raw, expected, shallow=False))

unittest.main(argv=["test_sphericalVideo"])
