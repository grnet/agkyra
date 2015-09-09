import os
import shutil

def main():
    os.chdir(os.path.dirname(os.path.realpath(__file__)))
    os.system("pip install certifi")

    print "Copying certifi's cacert.pem"
    import certifi
    shutil.copy2(certifi.where(), 'agkyra/resources/cacert.pem')


if __name__ == '__main__':
    main()
