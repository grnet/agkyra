from agkyra.syncer.setup import SyncerSettings
from agkyra.syncer.localfs_client import LocalfsFileClient
from agkyra.syncer.pithos_client import PithosFileClient
from agkyra.syncer.syncer import FileSyncer
from agkyra.syncer import messaging, utils
import random

from agkyra.config import AgkyraConfig, CONFIG_PATH

cnf = AgkyraConfig()
cloud_conf = cnf.get('cloud', 'test')
if cloud_conf is None:
    print "Define a 'test' cloud in %s" % CONFIG_PATH
    exit()

AUTHENTICATION_URL = cloud_conf['url']
TOKEN = cloud_conf['token']

ID = "AGKYRATEST" + str(random.random()).split('.')[1]

LOCAL_ROOT_PATH = "/tmp/" + ID


settings = SyncerSettings(
    instance=ID,
    auth_url=AUTHENTICATION_URL,
    auth_token=TOKEN,
    container=ID,
    local_root_path=LOCAL_ROOT_PATH,
    ignore_ssl=True)

master = PithosFileClient(settings)
slave = LocalfsFileClient(settings)
s = FileSyncer(settings, master, slave)

pithos = master.endpoint
pithos.create_container(ID)

f1 = "f1"
content1 = "content1"
r1 = pithos.upload_from_string(
    f1, content1)
etag1 = r1['etag']


pithos_cands = master.get_pithos_candidates()
info = pithos_cands[f1]
assert etag1 == info["pithos_etag"]

db = s.get_db()
state = db.get_state(master.SIGNATURE, f1)
assert state.serial == -1
assert state.info == {}

s.probe_file(master.SIGNATURE, f1)
m = s.get_next_message(block=True)
assert isinstance(m, messaging.UpdateMessage)

state = db.get_state(master.SIGNATURE, f1)
assert state.serial == 0
assert state.info == info

deciding = s.list_deciding()
assert deciding == set([f1])

state = db.get_state(slave.SIGNATURE, f1)
assert state.serial == -1
assert state.info == {}

s.decide_file_sync(f1)
m = s.get_next_message(block=True)
assert isinstance(m, messaging.SyncMessage)

m = s.get_next_message(block=True)
assert isinstance(m, messaging.AckSyncMessage)
state = db.get_state(slave.SIGNATURE, f1)
assert state.serial == 0
info = state.info
assert info['localfs_size'] == len(content1)

local_path = LOCAL_ROOT_PATH + '/' + f1
assert utils.hash_file(local_path) == utils.hash_string(content1)

def write_local():
    content2 = "content2"
    with open(local_path, "w") as f:
        f.write(content2)


def write_upstream():
    content3 = "content3"
    r3 = pithos.upload_from_string(
        f1, content3)
    etag3 = r1['etag']


def func():
    write_upstream()
    write_local()
    assert s.get_next_message() is None
    s.initiate_probe()
    s.start_decide()

    m = s.get_next_message(block=True)
    print m
    assert isinstance(m, messaging.UpdateMessage)
    assert m.archive == master.SIGNATURE

    m = s.get_next_message(block=True)
    print m
    assert isinstance(m, messaging.UpdateMessage)
    assert m.archive == slave.SIGNATURE

    m = s.get_next_message(block=True)
    print m
    assert isinstance(m, messaging.SyncMessage)

    m = s.get_next_message(block=True)
    print m
    assert isinstance(m, messaging.ConflictStashMessage)

    m = s.get_next_message(block=True)
    print m
    assert isinstance(m, messaging.AckSyncMessage)


func()
