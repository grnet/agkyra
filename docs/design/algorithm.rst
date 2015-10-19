How does it work
================

Agkyra falicitates synchronization between filesystem-like archives. In
particular, it currently supports synchronization between a local filesystem
directory and an object-store container.

It consists of three main modules: the syncer, which implements the logic of
deciding what to sync and managing the mechanism's state, and a client for
each one of the two archives, which are responsible for triggering and
applying syncer decisions.


Operation
---------

Agkyra runs three major operations, executed in separate threads:

* The first thread observes the local directory for modifications, using the
  'watchdog' package, which collects real-time notifications from the
  filesystem. The event handler records the modified file as a sync
  candidate in a dictionary.

* The second thread observes the Pithos container for changes. It
  periodically queries Pithos using the 'kamaki' library and lists container
  objects, recording changes since the last check as sync candidates.

* The third thread periodically probes the sync candidates collected by
  the other threads, decides what is to be synced and initiates the actual
  syncing in a new thread.

The state
---------

The syncer is built around a database, which keeps track of the state of
files and directories (collectively called 'objects') found in either
archive. The syncer also maintains a special 'SYNC' archive in the database,
which stores for each object the last acknowledged state that was
synchronized across the actual archives.

Probing an object
-----------------

Probing an object for an archive is delegated by the syncer to the
respective client module. The client observes the live state of the object
and checks whether this has changed since the last known state in the
database. In case of a change, the syncer acknowledges the existence of a
new version for the object by updating the object's entry for the given
archive in the database: it increases its serial number and stores the newly
found object metadata.

Deciding a sync
---------------

The syncer determines which objects need syncing by querying the database
for objects whose serial number for an archive is greater than the stored
SYNC serial. Then it determines the direction of the sync needed and marks
the new serial as decided by storing it in another special archive,
'DECISION'. Note that if an object has changed both in the local filesystem
and in the Pithos object-store, then the latter is given higher priority, as
it is considered the 'master' archive.) Finally, the syncer initiates the
syncing in a new thread.

Syncing an object
-----------------

Syncing consists of several steps. First, the client which operates the
source archive must prepare the object for transfer ('stage' it). Then the
target client pulls and applies the object to the target archive. The source
object is unstaged and, if syncing has succeeded, the target client calls
back the syncer to acknowledge the new sync state. The target and SYNC
archive entries for the object are updated to contain the new serial and
object metadata.

Avoiding overriding of unsynced objects
---------------------------------------

Object upload and download is facilitated by the kamaki library, which
implements the object-storage API. When uploading an object or deleting an
upstream one, the action is dependent on the last known upstream version
(etag) of the object. In case a new version is found upstream, the action
fails, in order not to override the new unsynced upstream version. Likewise,
when applying a downloaded object to the file system, a combination of file
system operations is used (first moving the existing file to a temporary
'hide' location and then linking the downloaded file back to the original
location).

Handling conflicts
------------------

If an object has changed in both archives since the last syncing, then there
is a conflict situation. The conflict is resolved by choosing to sync the
upstream version, while maintaining the local copy with a new name that
indicates the conflict.

Recovering from errors
----------------------

A syncing may fail for various reasons, for instance due to a connection or
a file system error. In this case, the stored DECISION serial will differ
from the SYNC serial, indicating that syncing has not completed. The
decision process will detect it and resume the syncing. However, since the
decision process is run often, it will also detect syncings that have not
completed because they are just still running. In order to distinguish and
exclude them, we keep in memory a 'heartbeat' entry for each active syncing
-- while an object is being transferred, the tranferring client is
responsible to keep the heartbeat up-to-date.

When syncing an upstream object to the local file system, there is a risk to
lose the local object if syncing fails after the object has been hidden, as
explained above. In order to address this, we record the file move to the
database, so that we can recover the file when syncing resumes.

Algorithm sketch
================

::

    archive serial: last recorded version of an object in an archive
    sync serial: the last synced version
    decision serial: specifies which version is being / should be synced

    failed serials: marks failed syncs to avoid replay (eg collision in upload)
      (in runtime -- in a new process replay will fail again)

    heartbeat: blocks probe while syncing, but candidates are kept for later
      blocks new sync action while syncing


    probe_file:
      if recent heartbeat for object found:
        abort (object is being synced)

      if archive serial != sync serial:
        abort (already probed)

      if object changed:
         get new info
         update object state
         commit


    decide_file_sync:
      if recent heartbeat found with different id:
        abort (already syncing)

      if previous decision serial found:
        use decision unless serial marked as failed

      make decision with priority to master
      add object/current id in heartbeat
      commit
      sync_file (in new thread)


    sync_file:
      source handle <- stage source object
      target pull file from source handle
      call back ack_file_sync (or mark_as_failed on failure)


    ack_file_sync (synced source state, synced target state):
      update source state
      update target state using source serial
      update sync state (merging source & target info) using source serial
      set decision state equal to sync state
      commit
      remove object from heartbeat


    mark_as_failed:
      remove object from heartbeat
      include (serial, file) in failed serials


    main loop:
      for every archive, probe candidate files
      for every file with updated serial, decide sync
