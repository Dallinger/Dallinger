import os
import sys
from setuptools import setup, find_packages


if sys.argv[-1] == "publish":
    os.system("python setup.py sdist upload")
    sys.exit()


setup_args = dict(
    name="dlgr.demos",
    version="5.0.7",
    description="Demonstration experiments for Dallinger",
    url="http://github.com/Dallinger/Dallinger",
    maintainer="Jordan Suchow",
    maintainer_email="suchow@berkeley.edu",
    license="MIT",
    keywords=["science", "cultural evolution", "experiments", "psychology"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    packages=find_packages("."),
    package_dir={"": "."},
    namespace_packages=["dlgr"],
    include_package_data=True,
    zip_safe=False,
    install_requires=["setuptools"],
    entry_points={
        "dallinger.experiments": [
            "Bartlett1932 = dlgr.demos.bartlett1932.experiment:Bartlett1932",
            "TwentyFortyEight = dlgr.demos.twentyfortyeight.experiment:TwentyFortyEight",
            "CoordinationChatroom = dlgr.demos.chatroom.experiment:CoordinationChatroom",
            "ConcentrationGame = dlgr.demos.concentration.experiment:ConcentrationGame",
            "FunctionLearning = dlgr.demos.function_learning.experiment:FunctionLearning",
            "IteratedDrawing = dlgr.demos.iterated_drawing.experiment:IteratedDrawing",
            "MCMCP = dlgr.demos.mcmcp.experiment:MCMCP",
            "RogersExperiment = dlgr.demos.rogers.experiment:RogersExperiment",
            "SheepMarket = dlgr.demos.sheep_market.experiment:SheepMarket",
            "SnakeGame = dlgr.demos.snake.experiment:SnakeGame",
            "VoxPopuli = dlgr.demos.vox_populi.experiment:VoxPopuli",
        ]
    },
)

setup(**setup_args)
