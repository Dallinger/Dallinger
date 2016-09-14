#!/usr/bin/python
import base64 
import sys

png_recovered = base64.decodestring(open(sys.argv[1],"rb").read())
f = open(sys.argv[1] + ".png", "w")
f.write(png_recovered)
f.close()