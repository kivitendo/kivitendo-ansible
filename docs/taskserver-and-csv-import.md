# kivitendo task server and CSV import hardening

This runbook captures the operational findings from enabling the kivitendo task server and importing service articles.

## Task server

kivitendo modules such as CSV import may require the background job daemon. A working Linux service is necessary but not sufficient: the kivitendo client/mandator must also be configured in the web UI.

### Server-side setup

After the kivitendo authentication database, client database and initial application user have been created in the web UI, run:

```bash
ansible-playbook \
  -i inventory \
  --ask-vault-pass \
  -e @secrets.yml \
  post-init-task-server.yml
```

For a local root-based deployment, `--ask-become-pass` is normally not required.

The post-init playbook performs the server-side setup that was validated manually:

- sets `[task_server] run_as = www-data` in `config/kivitendo.conf`;
- keeps `[task_server] debug = 0`;
- ensures `users`, `spool` and `webdav` are writable by `www-data:www-data`;
- installs `/etc/systemd/system/kivitendo-task-server.service` with `WorkingDirectory=/var/www/kivitendo-erp`;
- enables and starts the service;
- verifies systemd reports `active/running`;
- verifies `task_server.pl status` reports `kivitendo-background-jobs running` as the `www-data` user.

Useful manual checks:

```bash
systemctl status kivitendo-task-server.service --no-pager
cd /var/www/kivitendo-erp
runuser -u www-data -- ./scripts/task_server.pl status
journalctl -u kivitendo-task-server.service -n 150 --no-pager
```

`sudo` is not required when already logged in as root. On minimal Debian systems `sudo` may not be installed.

### Mandatory kivitendo web UI step

After the server-side service is running, open the kivitendo administration UI:

```text
Administration -> Mandantenverwaltung -> Mandant bearbeiten
```

Set:

```text
Task-Server für diesen Mandanten mit der folgenden BenutzerIn ausführen
```

to a kivitendo application user. This user is not the Linux user `www-data` and not the PostgreSQL role `kivitendo`. Use a dedicated technical kivitendo user when possible.

## CSV import safety

The error below usually means kivitendo parsed a quoted field with the wrong delimiter or received free-text data containing problematic quote/newline characters:

```text
EIF - Loose unescaped quote
```

For service-article imports, normalize the CSV before uploading it to kivitendo:

```bash
python3 scripts/normalize-kivitendo-csv.py \
  dynaris_kivitendo_dienstleistungsartikel.csv \
  dynaris_kivitendo_dienstleistungsartikel_kivitendo_safe.csv
```

The normalizer writes a deliberately conservative file:

- UTF-8 without BOM;
- semicolon-separated fields;
- no double quotes anywhere in the output;
- no embedded newlines or tabs in fields;
- semicolons inside free text are replaced with commas;
- double quotes inside free text are replaced with single quotes;
- CRLF line endings for broad web-import compatibility;
- fixed seven-column validation for the default article import structure:
  `partnumber`, `description`, `partsgroup`, `unit`, `sellprice`, `listprice`, `longdescription`.

When importing in kivitendo, use:

```text
Encoding: UTF-8
Field separator: ;
Text quote / enclosure: none or "
Decimal separator: ,
First row contains headers: yes
```

Because the normalized file contains no double quotes, a quote/enclosure mismatch in the UI cannot trigger the loose-unescaped-quote failure again for these generated article imports.
