# Test installation on a separate LMS server

Use a separate **LMS 9.2.0+** server for the first installation test. The plugin declares LMS 9.1.0 as its minimum, but full plugin operation has only been verified on LMS 9.2/Linux x86_64; binaries for the other CI platforms have only passed extension load tests. Check [compatibility](compatibility.md) before trying another platform. Keep your production LMS configuration and database out of this test.

## Plugin manager installation

1. Open **Settings > Plugins** in LMS.
2. Add `https://raw.githubusercontent.com/oweitman/LMS-PhoneticSearch/main/public.xml` under **Additional repositories** and save.
3. Reload the page, select **PhoneticSearch**, apply the installation, and restart LMS when prompted.
4. Open the plugin's **Settings** link. Wait for the index state to become `ready`.

The catalog points to the versioned ZIP on the [release page](https://github.com/oweitman/LMS-PhoneticSearch/releases/latest) and supplies the ZIP's SHA-1 checksum for LMS verification. The repository must be publicly accessible for an anonymous LMS server to download it.

## Manual test installation

Download the versioned `PhoneticSearch-<version>.zip` from the [release page](https://github.com/oweitman/LMS-PhoneticSearch/releases/latest). The release ZIP has `install.xml` at its root. Extract its contents into a **PhoneticSearch** directory under a plugin path listed by your LMS instance under **Settings > Information**. Stop only the test LMS before changing plugin files, then start it again. On some Docker images, `/config/cache/Plugins/PhoneticSearch/` is a manual plugin path; verify the actual plugin paths for your image before using it.

Do not manually place a plugin under `InstalledPlugins/Plugins`: LMS manages that directory and may remove unregistered contents on restart. Do not reuse a production LMS database for this test. The plugin reads `library.db` and writes its own index under the LMS cache.

## Verify the installation

Replace `LMS_HOST` with the test server address:

```sh
curl -sS -H 'Content-Type: application/json' \
  --data '{"id":1,"method":"slim.request","params":["",["phoneticsearch","status","?"]]}' \
  'http://LMS_HOST:9000/jsonrpc.js'
```

The result should eventually contain `"state":"ready"`. Try an artist from your own **test** music library with the search example in the [README](../README.md). During a scan, `updating` can be expected.

To remove a test installation and its index, use **Remove plugin data** on the plugin settings page, confirm with `DELETE`, wait for `cleanup_complete`, then stop the test LMS and remove the plugin. If the plugin remains installed, the next start recreates its index. An automatic LMS pre-uninstall hook has not been confirmed.
