import os
import sys
import shutil
import urllib

VERSION="v0.12.3"

nwjsfile = {
    "win64": "nwjs-%s-win-x64.zip",
    "osx64": "nwjs-%s-osx-x64.zip",
    "linux64": "nwjs-%s-linux-x64.tar.gz",
    "win32": "nwjs-%s-win-ia32.zip",
    "osx32" : "nwjs-%s-osx-ia32.zip",
    "linux32": "nwjs-%s-linux-ia32.tar.gz",
}

def main():
    os.chdir(os.path.dirname(os.path.realpath(__file__)))

    if len(sys.argv) < 2:
        print "Select one of: %s" % " ".join(nwjsfile.keys())
        exit(1)

    osarg = sys.argv[1]
    filename = nwjsfile[osarg] % VERSION
    url = "http://dl.nwjs.io/%s/%s" % (VERSION, filename)

    print "Will first download nwjs."
    target = "agkyra/resources/nwjs"
    if os.path.isdir(target):
        print "Warning: cleaning up %s." % target
        shutil.rmtree(target)
    elif os.path.exists(target):
        print "%s exists and is not a dir; aborting." % target
        exit(1)

    print "Retrieving %s" % url
    urllib.urlretrieve(url, filename)

    print "Extracting %s" % filename
    if osarg.startswith("linux"):
        toplevel = filename.strip('.tar.gz')
        os.system("tar xzf %s" % filename)
        print "Renaming %s to %s" % (toplevel, target)
        os.rename(toplevel, target)
    else:
        toplevel = filename.strip('.zip')
        if osarg.startswith('osx'):
            os.system("unzip %s" % filename)
        else:  # Windows has no unzip command
            import zipfile
            with zipfile.ZipFile(filename, "r") as z:
                z.extractall('.')
        print "Renaming %s to %s" % (toplevel, target)
        os.rename(toplevel, target)

    print "Deleting %s" % filename
    os.unlink(filename)


if __name__ == "__main__":
    main()
