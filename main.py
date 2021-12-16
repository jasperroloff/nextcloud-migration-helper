import configparser
import os.path
import logging
import zoneinfo
import urllib.parse
from typing import Dict

import nextcloud.api_wrappers
import nextcloud.common
from nextcloud import NextCloud
from sqlalchemy.orm import Session

from db import init_db, FileInfo
from utils import string_from_datetime


class NextcloudMigrationHelper:
    session: Session

    old_nc: NextCloud
    old_webdav_wrapper: nextcloud.api_wrappers.WebDAV
    old_share_wrapper: nextcloud.api_wrappers.Share
    old_sub_folder: str
    old_nc_url: str

    new_nc: NextCloud
    new_webdav_wrapper: nextcloud.api_wrappers.WebDAV
    new_share_wrapper: nextcloud.api_wrappers.Share
    new_sub_folder: str
    new_nc_username: str
    new_nc_url: str

    local_tmp_dir: str
    remote_folder_fs_path: str
    server_tz: zoneinfo.ZoneInfo

    def __init__(
            self,
            old_nc_url: str,
            old_nc_username: str,
            old_nc_password: str,
            new_nc_url: str,
            new_nc_username: str,
            new_nc_password: str,
            remote_folder_fs_path: str,
            server_tz: zoneinfo.ZoneInfo,
            old_sub_folder: str = "/",
            new_sub_folder: str = "/",
            local_tmp_dir: str = "tmp",
    ):
        self.old_nc = NextCloud(endpoint=old_nc_url, user=old_nc_username, password=old_nc_password)
        self.old_webdav_wrapper = nextcloud.api_wrappers.WebDAV(client=self.old_nc)
        self.old_share_wrapper = nextcloud.api_wrappers.Share(client=self.old_nc)
        self.old_sub_folder = old_sub_folder
        self.old_nc_url = old_nc_url
        if self.old_nc_url.endswith("/"):
            self.old_nc_url = self.old_nc_url[:-1]
        if not self.old_sub_folder.endswith("/"):
            self.old_sub_folder += "/"
        if not self.old_sub_folder.startswith("/"):
            self.old_sub_folder = "/" + self.old_sub_folder

        self.new_nc = NextCloud(endpoint=new_nc_url, user=new_nc_username, password=new_nc_password)
        self.new_webdav_wrapper = nextcloud.api_wrappers.WebDAV(client=self.new_nc)
        self.new_share_wrapper = nextcloud.api_wrappers.Share(client=self.new_nc)
        self.new_sub_folder = new_sub_folder
        self.new_nc_username = new_nc_username
        self.new_nc_url = new_nc_url
        if self.new_nc_url.endswith("/"):
            self.new_nc_url = self.new_nc_url[:-1]
        if not self.new_sub_folder.endswith("/"):
            self.new_sub_folder += "/"
        if not self.new_sub_folder.startswith("/"):
            self.new_sub_folder = "/" + self.new_sub_folder

        self.local_tmp_dir = local_tmp_dir

        self.remote_folder_fs_path = remote_folder_fs_path
        if not self.remote_folder_fs_path.endswith("/"):
            self.remote_folder_fs_path += "/"

        self.server_tz = server_tz

        db_path = os.path.join(self.local_tmp_dir, "files.db")
        self.session = init_db(f"sqlite+pysqlite:///{db_path}")

        logging.info("initialized")

    def _index_recursive(self, root: nextcloud.api_wrappers.webdav.File, parent: FileInfo = None):
        relative_path = root.get_relative_path()
        shares = self.old_share_wrapper.get_shares_from_path(relative_path).data

        file = self.session.query(FileInfo).filter_by(old_file_id=root.file_id).first() or FileInfo()
        file.name = root.basename()
        file.size = 0 if file.is_dir else root.size
        file.old_file_id = root.file_id
        file.old_relative_path = root.get_relative_path()
        file.last_modified = root.last_modified_datetime
        file.is_dir = root.isdir()
        file.parent_id = parent.id if parent else None
        file.shared = len(shares) > 0
        file.update_new_relative_path(self.old_sub_folder, self.new_sub_folder)

        self.session.add(file)

        if root.isdir() and (file.was_modified() or not file.indexing_finished):
            self.session.add(file)
            self.session.commit()

            logging.info("indexing dir %s", file.old_relative_path)

            children = root.list(all_properties=True)

            for child in children:
                self._index_recursive(child, parent=file)

        if not file.indexing_finished:
            file.indexing_finished = True
            self.session.add(file)

        self.session.commit()

    def build_index(self):
        logging.warning("start building index")
        old_root = self.old_webdav_wrapper.get_folder(self.old_sub_folder or '/', all_properties=True)
        self._index_recursive(old_root)
        logging.warning("finished building index")

    def _fetch_new_file_ids_recursive(self, root: nextcloud.api_wrappers.webdav.File):
        relative_path = root.get_relative_path()

        file = self.session.query(FileInfo).filter_by(new_relative_path=relative_path).first()
        if not file:
            # could happen if there are manual file uploads while this script is running
            logging.warning("couldn't find new file in database")
            return

        file.new_file_id = root.file_id
        self.session.add(file)

        if root.isdir() and file.was_modified():
            logging.info("fetching file_ids in dir %s", file.new_relative_path)

            children = root.list(all_properties=True)

            for child in children:
                self._fetch_new_file_ids_recursive(child)

        self.session.commit()

    def fetch_new_file_ids(self):
        logging.warning("start fetching new file_ids")
        new_root = self.new_webdav_wrapper.get_folder(self.new_sub_folder or '/', all_properties=True)
        self._fetch_new_file_ids_recursive(new_root)
        logging.warning("finished fetching new file_ids")

    def _build_tree(self, root: FileInfo) -> Dict:
        return self._build_tree_recursive(root)

    def _build_tree_recursive(self, file: FileInfo) -> Dict:
        tree = dict()

        for child in file.children:
            child: FileInfo

            if child.is_dir:
                tree[child.name] = self._build_tree_recursive(child)

        return tree

    def _move_recursive(self, file: FileInfo):
        if not file.uploaded:
            if file.is_dir:
                logging.info("uploading dir %s", file.old_relative_path)

                # ensure folder exists
                self.new_webdav_wrapper.ensure_folder_exists(file.new_relative_path)

                # upload content
                for child in file.children:
                    child: FileInfo

                    self._move_recursive(child)

                # set modified date
                self._set_modified_date(file)
            else:
                tmp_path = self._get_local_temp_path(file)

                if not file.downloaded or not os.path.exists(tmp_path):
                    self.old_webdav_wrapper.download_file(file.old_relative_path, tmp_path, True)
                    file.downloaded = True
                    self.session.add(file)
                    self.session.commit()

                self.new_webdav_wrapper.upload_file(tmp_path, file.new_relative_path)
                os.remove(tmp_path)

            file.uploaded = True

            self.session.add(file)
            self.session.commit()

    def _get_local_temp_path(self, file: FileInfo) -> str:
        return os.path.join(self.local_tmp_dir, str(file.id))

    def _set_modified_date(self, file: FileInfo):
        modified_date_str = string_from_datetime(file.last_modified)
        res = self.new_webdav_wrapper.set_file_property(
            file.new_relative_path,
            {"d": {"getlastmodified": modified_date_str}}
        )

    def create_folders(self):
        logging.warning("started creating folders")
        root = self.session.query(FileInfo).filter_by(parent=None).first()

        # create folder tree
        tree = dict()
        tree[self.new_sub_folder[:-1]] = self._build_tree(root)
        self.new_webdav_wrapper.ensure_tree_exists(tree)

        # set modified dates for folders – doesn't work :(
        for dir_file in self.session.query(FileInfo).filter_by(is_dir=True):
            self._set_modified_date(dir_file)

        logging.warning("finished creating folders")

    def move_files(self):
        logging.warning("start moving files")
        if not os.path.exists(self.local_tmp_dir):
            logging.warning("creating local temp dir")
            os.mkdir(self.local_tmp_dir)
        root = self.session.query(FileInfo).filter_by(parent=None).first()
        self._move_recursive(root)
        logging.warning("finished moving folders")

    def generate_dir_timestamp_script(self):
        with open(os.path.join(self.local_tmp_dir, "directory_timestamps.sh"), "w") as script_file:
            script_file.write("#!/bin/sh\n\n")

            for dir_file in self.session.query(FileInfo).filter_by(is_dir=True):
                dir_file: FileInfo

                full_path = os.path.join(self.remote_folder_fs_path, dir_file.new_relative_path[len(self.new_sub_folder):])
                escaped_path = "'" + full_path.replace("'", "'\\''") + "'"

                timestamp = dir_file.last_modified.astimezone(self.server_tz).strftime("%Y%m%d%H%M.%S")
                script_file.write(f"/usr/bin/touch -t {timestamp} {escaped_path}\n")

            script_file.write("\n")

            # generate command to trigger "occ files:scan" for sub folder
            path_param = f"/{self.new_nc_username}/files{self.new_sub_folder}"
            path_param = "'" + path_param.replace("'", "'\\''") + "'"
            scan_cmd = f"occ files:scan --path={path_param}"
            scan_cmd_escaped = "'" + scan_cmd.replace("'", "'\\''") + "'"

            script_file.write(f"echo 'Run the following occ command to load the changes into Nextcloud:'\n")
            script_file.write(f"echo {scan_cmd_escaped}\n")

    def generate_nginx_redirect_config(self):
        with open(os.path.join(self.local_tmp_dir, "nginx.conf"), "w") as nginx_conf:
            nginx_conf.write(
                "map_hash_bucket_size 256; # see http://nginx.org/en/docs/hash.html\n"
                "map $request_uri $new_uri {\n"
                "   include old_new.map;\n"
                "}\n"
                "server {\n"
                "   listen 80;\n"
                "   server_name localhost;\n"
                "   if ($new_uri) {\n"
                "       return 301 $new_uri;\n"
                "    }\n"
                "}\n"
            )

        with open(os.path.join(self.local_tmp_dir, "old_new.map"), "w") as redirect_map:
            path_prefix = urllib.parse.urlparse(self.old_nc_url).path
            for file in self.session.query(FileInfo):
                redirect_map.write(f"{path_prefix}/f/{file.old_file_id} {self.new_nc_url}/f/{file.new_file_id}\n")

    def run(self):
        self.build_index()
        self.move_files()
        self.fetch_new_file_ids()
        # self.create_shares()
        self.generate_nginx_redirect_config()
        self.generate_dir_timestamp_script()


if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read('config.ini')

    logging.basicConfig(level=logging.INFO)

    helper = NextcloudMigrationHelper(
        old_nc_url=config.get("old_nextcloud", "url"),
        old_nc_username=config.get("old_nextcloud", "username"),
        old_nc_password=config.get("old_nextcloud", "password"),
        old_sub_folder=config.get("old_nextcloud", "sub_folder"),
        new_nc_url=config.get("new_nextcloud", "url"),
        new_nc_username=config.get("new_nextcloud", "username"),
        new_nc_password=config.get("new_nextcloud", "password"),
        new_sub_folder=config.get("new_nextcloud", "sub_folder"),
        local_tmp_dir=config.get("other", "local_tmp_dir"),
        remote_folder_fs_path=config.get("other", "remote_folder_fs_path"),
        server_tz=zoneinfo.ZoneInfo(config.get("other", "server_tz")),
    )

    helper.run()
