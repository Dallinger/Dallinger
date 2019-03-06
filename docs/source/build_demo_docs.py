import tempfile
import os
import shutil
import subprocess as sp


def make_demo(name, src, dst, root):
    print("Making '{}' demo...".format(name))

    static_files = []
    for file in os.listdir(src):
        if file.endswith(".jpg") or file.endswith(".png"):
            shutil.copy(
                os.path.join(src, file),
                os.path.join(dst, file)
            )
            static_files.append(file)

    # convert and copy the README to the static location
    sp.call([
        "pandoc",
        "--from", "markdown",
        "--to", "rst",
        "-o", os.path.join(dst, "index.rst"),
        os.path.join(src, "README.md")
    ])

    # add a link to download the demo to the readme
    with open(os.path.join(dst, "index.rst"), "a") as fh:
        fh.write("\n\n")
        fh.write(
            "`Download the demos <{}/_static/{}.zip>`__.\n".format(
                os.path.relpath(root, dst), name
            )
        )

    # create a temporary directory
    tempdir = tempfile.mkdtemp()
    origdir = os.getcwd()
    os.chdir(tempdir)

    try:
        # Remove some tmp dirs in advance of copying
        unwanted = ['.tox', '__pycache__']
        for filename in unwanted:
            path = os.path.join(src, filename)
            if os.path.exists(path):
                shutil.rmtree(path)
        shutil.copytree(src, os.path.join(tempdir, name))

        # remove unnecessary files
        extra = ["snapshots", "server.log", '.vscode']
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

    src = os.path.abspath(os.path.join(root, "..", "..", "demos"))
    static_files = []
    if os.path.isdir(src):
        dst = os.path.join(root, "demos")
        static = make_demo("demos", src, dst, root)
        static_files.extend(
            [os.path.join("demos", x) for x in static])
    return static_files
