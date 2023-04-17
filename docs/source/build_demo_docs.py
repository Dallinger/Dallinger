import os
import shutil
import subprocess as sp
import tempfile


def make_demo(name, src, dst):
    print("Making '{}' demo...".format(name))

    static_files = []
    for file in os.listdir(src):
        if file.endswith(".jpg") or file.endswith(".png"):
            shutil.copy(os.path.join(src, file), os.path.join(dst, file))
            static_files.append(file)

    # convert and copy the README to the static location
    sp.call(
        [
            "pandoc",
            "--from",
            "markdown",
            "--to",
            "rst",
            "-o",
            os.path.join(dst, "index.rst"),
            os.path.join(src, "README.md"),
        ]
    )

    # add a link to download the demo to the readme
    with open(os.path.join(dst, "index.rst"), "a") as fh:
        fh.write("\n\n")
        fh.write("`Download the demo <../../_static/{}.zip>`__.\n".format(name))

    # create a temporary directory
    tempdir = tempfile.mkdtemp()
    origdir = os.getcwd()
    os.chdir(tempdir)

    try:
        shutil.copytree(src, os.path.join(tempdir, name))

        # remove unnecessary files
        extra = ["snapshots", "server.log"]
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
        shutil.copy(os.path.join(tempdir, zipname), os.path.join(dst, zipname))
        static_files.append(zipname)

    finally:
        # remove the temporary directory
        os.chdir(origdir)
        shutil.rmtree(tempdir)

    return static_files


def build(root):
    if not os.path.exists(os.path.join(root, "demos")):
        os.makedirs(os.path.join(root, "demos"))

    demos_dir = os.path.abspath(
        os.path.join(root, "..", "..", "demos", "dlgr", "demos")
    )
    static_files = []
    for demo in os.listdir(demos_dir):
        src = os.path.join(demos_dir, demo)
        if os.path.isdir(src):
            dst = os.path.join(root, "demos", demo)
            if not os.path.exists(dst):
                os.makedirs(dst)
            static = make_demo(demo, src, dst)
            static_files.extend([os.path.join("demos", demo, x) for x in static])

    return static_files
