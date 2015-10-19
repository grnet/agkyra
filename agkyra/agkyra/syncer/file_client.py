import logging
logger = logging.getLogger(__name__)

from agkyra.syncer import common


class FileClient(object):

    def list_candidate_files(self, archive):
        raise NotImplementedError

    def start_probing_path(self, path, old_state, ref_state, callback=None):
        raise NotImplementedError

    def stage_file(self, source_state):
        raise NotImplementedError

    def prepare_target(self, state):
        raise NotImplementedError

    def start_pulling_file(self, source_handle, target_state, sync_state,
                           callback=None):
        try:
            synced_source_state, synced_target_state = \
                self._start(source_handle, target_state, sync_state)
            if callback is not None:
                callback(synced_source_state, synced_target_state)
        except common.SyncError as e:
            logger.warning(e)

    def _start(self, source_handle, target_state, sync_state):
        try:
            target_handle = self.prepare_target(target_state)
            synced_target_state = target_handle.pull(source_handle, sync_state)
            synced_source_state = source_handle.get_synced_state()
            return synced_source_state, synced_target_state
        finally:
            source_handle.unstage_file()
