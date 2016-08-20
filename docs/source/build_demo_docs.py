import tempfile
import os
import shutil
import subprocess as sp


def make_example(name, src, dst):
    print("Making '{}'' example...".format(name))

    # convert and copy the README to the static location
    sp.call([
        "pandoc",
        "--from", "markdown",
        "--to", "rst",
        "-o", os.path.join(dst, "demos", "{}.rst".format(name)),
        os.path.join(src, "README.md")
    ])

    # add a link to download the demo to the readme
    with open(os.path.join(dst, "demos", "{}.rst".format(name)), "a") as fh:
        fh.write("\n\n")
        fh.write("`Download the demo <../_static/{}.zip>`__.\n".format(name))

    # create a temporary directory
    tempdir = tempfile.mkdtemp()
    origdir = os.getcwd()
    os.chdir(tempdir)

    try:
        shutil.copytree(src, os.path.join(tempdir, name))

        # remove unnecessary files
        extra = [".psiturk_history", "snapshots", "server.log"]
        for filename in extra:
            path = os.path.join(tempdir, name, filename)
            if os.path.exists(path):
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)

        # create the zip file
        zipname = "{}.zip".format(name)
        sp.call(["zip", "-r", zipname, name])

        # copy the zip file to the static location
        shutil.copy(os.path.join(tempdir, zipname), os.path.join(dst, "_static", zipname))

    finally:
        # remove the temporary directory
        os.chdir(origdir)
        shutil.rmtree(tempdir)


def build(root):
    if not os.path.exists(os.path.join(root, "demos")):
        os.makedirs(os.path.join(root, "demos"))

    examples_dir = os.path.abspath(os.path.join(root, "..", "..", "examples"))
    for example in os.listdir(examples_dir):
        src = os.path.join(examples_dir, example)
        if os.path.isdir(src):
            make_example(example, src, root)
