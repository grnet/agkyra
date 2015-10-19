import os
import hashlib
import datetime

BUF_SIZE = 65536


def join_path(dirpath, filename):
    if dirpath == ".":
        dirpath = ""
    return os.path.join(dirpath, filename)


def hash_string(s):
    return hashlib.sha256(s).hexdigest()


def hash_file(filename, block_size=BUF_SIZE):
    sha256 = hashlib.sha256()
    with open(filename, 'rb') as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest()


def time_stamp():
    return datetime.datetime.now().strftime("%s.%f")


def younger_than(tstamp, seconds):
    now = datetime.datetime.now()
    ts = datetime.datetime.fromtimestamp(int(float(tstamp)))
    delta = now - ts
    return delta < datetime.timedelta(seconds=seconds)
