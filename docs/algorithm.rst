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
