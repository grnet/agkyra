import os

def main():
    os.chdir(os.path.dirname(os.path.realpath(__file__)))

    import get_nwjs
    get_nwjs.main()
    import cacert_cp
    cacert_cp.main()
    import nwapp_version
    nwapp_version.main()

    print "Now run 'python setup.py install'."


if __name__ == '__main__':
    main()
