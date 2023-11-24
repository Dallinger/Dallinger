def patch_ipython():
    try:
        from ipykernel.iostream import OutStream
    except ImportError:
        return
    else:
        OutStream.writable = lambda self: True


def patch():
    patch_ipython()
