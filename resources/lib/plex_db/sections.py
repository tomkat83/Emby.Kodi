#!/usr/bin/env python
# -*- coding: utf-8 -*-

class Sections(object):
    def all_sections(self):
        """
        Returns an iterator for all sections
        """
        self.cursor.execute('SELECT * FROM sections')
        return (self.entry_to_section(x) for x in self.cursor)

    def section(self, section_id):
        """
        For section_id, returns the dict
            section_id INTEGER PRIMARY KEY,
            section_name TEXT,
            plex_type TEXT,
            kodi_tagid INTEGER,
            sync_to_kodi BOOL,
            last_sync INTEGER
        """
        self.cursor.execute('SELECT * FROM sections WHERE section_id = ? LIMIT 1',
                            (section_id, ))
        return self.entry_to_section(self.cursor.fetchone())

    @staticmethod
    def entry_to_section(entry):
        if not entry:
            return
        return {
            'section_id': entry[0],
            'section_name': entry[1],
            'plex_type': entry[2],
            'kodi_tagid': entry[3],
            'sync_to_kodi': entry[4] == 1,
            'last_sync': entry[5]
        }

    def section_id_by_name(self, section_name):
        """
        Returns the section_id for section_name (or None)
        """
        self.cursor.execute('SELECT section_id FROM sections WHERE section_name = ? LIMIT 1',
                            (section_name, ))
        try:
            return self.cursor.fetchone()[0]
        except TypeError:
            pass

    def add_section(self, section_id, section_name, plex_type, kodi_tagid,
                    sync_to_kodi, last_sync):
        """
        Appends a Plex section to the Plex sections table
        sync=False: Plex library won't be synced to Kodi
        """
        query = '''
            INSERT OR REPLACE INTO sections(
                section_id,
                section_name,
                plex_type,
                kodi_tagid,
                sync_to_kodi,
                last_sync)
            VALUES (?, ?, ?, ?, ?, ?)
            '''
        self.cursor.execute(query,
                            (section_id,
                             section_name,
                             plex_type,
                             kodi_tagid,
                             sync_to_kodi,
                             last_sync))

    def update_section(self, section_id, section_name):
        """
        Updates the section with section_id
        """
        query = 'UPDATE sections SET section_name = ? WHERE section_id = ?'
        self.cursor.execute(query, (section_name, section_id))

    def remove_section(self, section_id):
        """
        Removes the Plex db entry for the section with section_id
        """
        self.cursor.execute('DELETE FROM sections WHERE section_id = ?',
                            (section_id, ))

    def update_section_sync(self, section_id, sync_to_kodi):
        """
        Updates whether we should sync sections_id (sync=True) or not
        """
        if sync_to_kodi:
            query = '''
                UPDATE sections
                SET sync_to_kodi = ?
                WHERE section_id = ?
            '''
        else:
            # Set last_sync = 0 in order to force a full sync if reactivated
            query = '''
                UPDATE sections
                SET sync_to_kodi = ?, last_sync = 0
                WHERE section_id = ?
            '''
        self.cursor.execute(query, (sync_to_kodi, section_id))

    def update_section_last_sync(self, section_id, last_sync):
        """
        Updates the timestamp for the section
        """
        self.cursor.execute('UPDATE sections SET last_sync = ? WHERE section_id = ?',
                            (last_sync, section_id))

    def force_full_sync(self):
        """
        Sets the last_sync flag to 0 for every section
        """
        self.cursor.execute('UPDATE sections SET last_sync = 0')
