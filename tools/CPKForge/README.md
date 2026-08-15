# CPKForge

Standalone CPK builder for JoJo ASBR's `data.cpk` layout. The learned layout profile is embedded in the executable. It streams a complete input folder into a new archive, verifies all file ranges, and commits the result only after validation succeeds.

The input folder must contain the complete 3,642-file `data.cpk` file set. Files are stored uncompressed.

Double-click `CPKForge.exe` to open the graphical interface, or use these commands:

```text
CPKForge verify original.cpk
CPKForge build complete-data-folder output.cpk
CPKForge unpack archive.cpk output-folder
```
