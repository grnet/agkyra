Syncing files with Agkyra
=========================

Overview
--------

Agkyra will synchronize a local directory on your computer with a container
on your Pithos account. When you initialize a sync, Agkyra will download any
files and directories missing from the local directory, and upload any
missing from the Pithos container.

Agkyra will continuously observe your local file system and your Pithos
account for changes (new, modified or deleted files or directories) and do
the necessary transfers in order to make sure that your local directory and
your Pithos container will always be in sync.

What files are exempted
-----------------------

On your local directory, Agkyra creates directory `.agkyra_cache` during
initialization. This is used to temporarily store files during the process
of upload/download, and is not synced itself.

Applications sometimes make temporary files during their execution. Agkyra
recognizes certain filename patterns as indicative of temporary files and
does not sync them. Examples are files beginning with `.#` or `.~`, or
ending with `~`.

Resolving conflicts
-------------------

Agkyra takes care to preserve changes that appear either upstream or on the
local directory. If a file has changed both upstream and on your local
directory since the last successful synchronization, there is a confict
because Agkyra doesn't know how to merge these changes. It chooses to
download the upstream file, but also preserve the locally changed file, with
name `<filename>_<timestamp>_<computername>`, which at the next syncing step
will be uploaded, too.

Handling special files
----------------------

Only regular files and directories are synced upstream. Unix-style symbolic
links found on the local directory are not synced. However, if a namesake
regular file is found upstream and must be downloaded, Agkyra takes care to
resolve this conflict and preserve the existing symbolic link as above.

Note that handling Unix-style hard links is not supported.

Case-sensitivity
----------------

Pithos object-storage is case sensitive. This means that, for example, files
`filename` and `FileName` can appear upstream at the same time. Windows and
OSX filesystems are not case sensitive, and cannot store two files whose
name differ only by case. If such files appear upstream, then the first one
is downloaded as usually while the second one causes a conflict and is
stored with a conflict name, as explained above. At the next syncing
iteration, the name change will be propagated upstream.
