# Packs each group of three consecutive input frames into one output frame, by
# converting each input frame to grayscale and puting input frame i into one
# channel of the output frame (e.g., red), input frame i+1 into another channel
# (e.g., green), and i+2 into another channel (e.g., blue).

# Run in Blender, e.g.:
# blender --background --python packFrames.py -- -i path/inputFrames -o path/outputFrames

import argparse
import bpy
import datetime
import os
import os.path
import sys
import time

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
from utilsFormats import fileFormatToExt, unknownFormatErrorMessage

def setupImageNodes(i):
    tree = bpy.context.scene.node_tree
    treeLinks = tree.links

    imageNode = tree.nodes.new(type="CompositorNodeImage")
    imageNode.name = "image" + str(i)
    toBWNode = tree.nodes.new(type="CompositorNodeRGBToBW")
    toBWNode.name= "toBW" + str(i)
    treeLinks.new(imageNode.outputs["Image"], toBWNode.inputs["Image"])

    return (imageNode, toBWNode)

def setupNodes(outputFormat, packedOrder):
    bpy.context.scene.use_nodes = True
    tree = bpy.context.scene.node_tree
    treeLinks = tree.links

    for node in tree.nodes:
        tree.nodes.remove(node)

    (imageNode0, toBWNode0) = setupImageNodes(0)
    (imageNode1, toBWNode1) = setupImageNodes(1)
    (imageNode2, toBWNode2) = setupImageNodes(2)

    combineNode = tree.nodes.new(type="CompositorNodeCombRGBA")
    combineNode.name = "combine"
    treeLinks.new(toBWNode0.outputs["Val"], combineNode.inputs[packedOrder[0]])
    treeLinks.new(toBWNode1.outputs["Val"], combineNode.inputs[packedOrder[1]])
    treeLinks.new(toBWNode2.outputs["Val"], combineNode.inputs[packedOrder[2]])

    outputNode = tree.nodes.new(type="CompositorNodeOutputFile")
    outputNode.format.file_format = outputFormat.upper()
    treeLinks.new(combineNode.outputs["Image"], outputNode.inputs["Image"])

    return (imageNode0, imageNode1, imageNode2, outputNode)

def findInputFrames(inputDir, start, end):
    inFrames = [f for f in os.listdir(inputDir) if os.path.splitext(f)[0].isdigit()]
    inFrames = [f for f in inFrames if start <= int(os.path.splitext(f)[0]) and int(os.path.splitext(f)[0]) <= end]
    inFrames.sort()

    # The pack() function is simpler if it can assume the frame count is a multiple of three.
    # So if it is not, duplicate the final frame until it is.
    while len(inFrames) % 3 > 0:
        inFrames.append(inFrames[-1])

    return inFrames

def setupRender():
    bpy.context.scene.render.resolution_percentage = 100
    bpy.context.scene.render.pixel_aspect_x = 1
    bpy.context.scene.render.pixel_aspect_y = 1
    bpy.context.scene.render.use_compositing = True

def pack(inputDir, inputFrames, imageNodes, outputNode, outputDir, outputExt):
    for imageNode in imageNodes:
        if imageNode.image:
            bpy.data.images.remove(imageNode.image)

    i = 0
    for inputFrame in inputFrames:
        if i == 0:
            outputFrame = os.path.splitext(inputFrame)[0]
            outputPath = os.path.join(outputDir, outputFrame) + outputExt
        if i < 3:
            inputPath = os.path.join(inputDir, inputFrame)
            imageNodes[i].image = bpy.data.images.load(inputPath)
        i += 1
        if i == 3:
            i = 0

            outputNode.base_path = os.path.join(outputDir, outputFrame)
            bpy.ops.render.render()

            # Necessary to workaround problems directly setting the output file name.
            if os.path.exists(outputPath):
                os.remove(outputPath)
            os.rename(os.path.join(outputNode.base_path, "Image0001") + outputExt, outputPath)
            os.rmdir(outputNode.base_path)

if __name__ == "__main__":
    timeStart = datetime.datetime.now()
    argv = sys.argv
    if "--" not in argv:
        argv = []
    else:
        argv = argv[argv.index("--") + 1:]

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", dest="inputDir", help="path to the directory containing the input frames")
    parser.add_argument("--output", "-o", dest="outputDir", help="path for the output packed frames")
    parser.set_defaults(packedOrder="RGB")
    parser.add_argument("--packedOrder", "-po", dest="packedOrder", help="packing order (e.g., 'RGB' means frame 0 in R, 1 in G, 2 in B)")
    parser.set_defaults(outputFormat="bmp")
    parser.add_argument("--outputFormat", "-of", dest="outputFormat", help="image format for output")
    parser.set_defaults(start=1)
    parser.add_argument("--start", "-s", dest="start", type=int, help="first frame to comp")
    parser.set_defaults(end=999999)
    parser.add_argument("--end", "-e", dest="end", type=int, help="last frame to comp")
    args = parser.parse_args(argv)

    outputFormat = args.outputFormat.upper()
    if not outputFormat in fileFormatToExt:
        print(unknownFormatErrorMessage(args.outputFormat))
        quit()
    outputExt = fileFormatToExt[outputFormat]
    print("Using output format: {}".format(outputFormat))

    packedOrder = args.packedOrder.upper()
    print("Using packed order: {}".format(packedOrder))

    if args.inputDir == None:
        parser.print_help()
        quit()
    outputDir = args.outputDir
    if outputDir == None:
        outputDir = args.inputDir
    if outputDir[:-1] != "/":
        outputDir += "/"
    print("Using output directory: {}".format(outputDir))

    inputFrames = findInputFrames(args.inputDir, args.start, args.end)
    (imageNode0, imageNode1, imageNode2, outputNode) = setupNodes(outputFormat, packedOrder)
    imageNodes = [imageNode0, imageNode1, imageNode2]
    setupRender()
    pack(args.inputDir, inputFrames, imageNodes, outputNode, args.outputDir, outputExt)

    timeEnd = datetime.datetime.now()
    print("Packing started at {}".format(timeStart))
    print("Packing ended at {}".format(timeEnd))
