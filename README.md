# Nextcloud Migration Helper

Small tool to help when moving from one Nextcloud instance to another

## About

This tool helps when moving one Nextcloud instance to another.
It is also possible to only migrate a sub folder.

This tool

* generates a list of all files (together with timestamp, path, file_id, ...)
* uploads all files to the new instance
* generates a script to modify the timestamps of directories (because this can't be done via API/WebDav)

## Installation

1. First, `git clone` this repo and select into the cloned dir

```
git clone https://github.com/jasperroloff/nextcloud-migration-helper.git
cd nextcloud-migration-helper/
```

2. Create the configuration file:

There is an example config file `config.sample.ini`.
Copy this file to `config.ini` and change the values to your needs.

3. Create python venv (optional):

```
python -m venv venv
source venv/bin/activate
```

4. Install dependencies:

```
pip install -r requirements.txt
```

## Usage

Simply execute the `main.py` python file:

```
python main.py
```

## Tips

### Resume after interrupt

If you have to interrupt the program (e.g. because of network issues), you can simply start it again. It should then resume where it stopped.

### Clean start

To do a clean start, just delete the local tmp directory or the `files.db` file in it.

### Show progress

While uploading, the progress can be viewed by doing the following query against the database file:

```
select printf('%.2f %%', avg(uploaded)*100) as progress from files;
```

## License

See [here](./LICENSE.md)
