using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Drawing;
using System.Windows.Forms;
using System.Reflection;
using CriPakTools;

namespace CPKForge
{
    internal static class Program
    {
        private const int CopyBufferSize = 1024 * 1024;

        [STAThread]
        private static int Main(string[] args)
        {
            try
            {
                if (args.Length == 0)
                {
                    Application.EnableVisualStyles();
                    Application.SetCompatibleTextRenderingDefault(false);
                    Application.Run(new ForgeForm());
                    return 0;
                }

                if (args[0] == "--help" || args[0] == "-h")
                {
                    PrintUsage();
                    return 0;
                }

                if (args[0].Equals("verify", StringComparison.OrdinalIgnoreCase) && args.Length == 2)
                {
                    Verify(args[1]);
                    Console.WriteLine("OK: archive structure and file ranges are valid.");
                    return 0;
                }

                if (args[0].Equals("compare", StringComparison.OrdinalIgnoreCase) && args.Length == 3)
                {
                    ComparePayloads(args[1], args[2]);
                    Console.WriteLine("OK: every archived payload is byte-identical.");
                    return 0;
                }

                if (args[0].Equals("rebuild", StringComparison.OrdinalIgnoreCase) && args.Length == 4)
                {
                    Rebuild(args[1], args[2], args[3], null, false);
                    return 0;
                }

                if (args[0].Equals("build", StringComparison.OrdinalIgnoreCase) && args.Length == 3)
                {
                    StandaloneBuild(args[1], args[2], null);
                    return 0;
                }

                if (args[0].Equals("unpack", StringComparison.OrdinalIgnoreCase) && args.Length == 3)
                {
                    Unpack(args[1], args[2], null);
                    return 0;
                }

                if (args[0].Equals("inspect", StringComparison.OrdinalIgnoreCase) && args.Length == 3)
                {
                    Inspect(args[1], args[2]);
                    return 0;
                }

                PrintUsage();
                return 2;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("ERROR: " + ex.Message);
                return 1;
            }
        }

        private static void PrintUsage()
        {
            Console.WriteLine("CPKForge - compatibility-first CPK rebuilder");
            Console.WriteLine("  CPKForge verify <archive.cpk>");
            Console.WriteLine("  CPKForge compare <first.cpk> <second.cpk>");
            Console.WriteLine("  CPKForge rebuild <original.cpk> <replacement-folder> <output.cpk>");
            Console.WriteLine("  CPKForge build <complete-data-folder> <output.cpk>");
            Console.WriteLine("  CPKForge unpack <archive.cpk> <output-folder>");
            Console.WriteLine("  CPKForge inspect <archive.cpk> <report.txt>");
            Console.WriteLine("The original is used as a metadata template. Missing replacements are copied unchanged.");
        }

        private static CPK Open(string path)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("CPK not found", path);
            var cpk = new CPK(new Tools());
            if (!cpk.ReadCPK(path)) throw new InvalidDataException("Unsupported or damaged CPK: " + path);
            return cpk;
        }

        private static void Verify(string path)
        {
            var cpk = Open(path);
            long length = new FileInfo(path).Length;
            var files = cpk.FileTable.Where(e => e.FileType == "FILE").ToList();
            if (files.Count == 0) throw new InvalidDataException("Archive contains no file entries.");

            foreach (var entry in files)
            {
                ulong size = Convert.ToUInt64(entry.FileSize, CultureInfo.InvariantCulture);
                if (entry.FileOffset > (ulong)length || size > (ulong)length - entry.FileOffset)
                    throw new InvalidDataException("Out-of-range entry: " + EntryPath(entry));
            }
        }

        private static void Rebuild(string templatePath, string replacementRoot, string outputPath, Action<int, string> progress, bool encryptReplacements)
        {
            templatePath = Path.GetFullPath(templatePath);
            replacementRoot = Path.GetFullPath(replacementRoot);
            outputPath = Path.GetFullPath(outputPath);
            if (!Directory.Exists(replacementRoot)) throw new DirectoryNotFoundException(replacementRoot);
            if (String.Equals(templatePath, outputPath, StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("Output must differ from the original template.");

            var cpk = Open(templatePath);
            ushort alignment = Convert.ToUInt16(cpk.cpkdata["Align"], CultureInfo.InvariantCulture);
            if (alignment == 0) throw new InvalidDataException("Template has zero alignment.");

            string outputDir = Path.GetDirectoryName(outputPath);
            if (!String.IsNullOrEmpty(outputDir)) Directory.CreateDirectory(outputDir);
            string tempPath = outputPath + ".building-" + Guid.NewGuid().ToString("N") + ".tmp";
            int replaced = 0;

            try
            {
                using (var source = new FileStream(templatePath, FileMode.Open, FileAccess.Read, FileShare.Read, CopyBufferSize, FileOptions.SequentialScan))
                using (var destination = new FileStream(tempPath, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.None, CopyBufferSize, FileOptions.SequentialScan))
                using (var writer = new BinaryWriter(destination))
                {
                    var orderedEntries = cpk.FileTable.OrderBy(e => e.FileOffset).ToList();
                    for (int entryIndex = 0; entryIndex < orderedEntries.Count; entryIndex++)
                    {
                        var entry = orderedEntries[entryIndex];
                        if (progress != null) progress(entryIndex * 95 / Math.Max(1, orderedEntries.Count), EntryPath(entry));
                        ulong originalOffset = entry.FileOffset;
                        if (entry.FileType == "CONTENT")
                        {
                            cpk.UpdateFileEntry(entry);
                            continue;
                        }
                        if (entry.FileType == "FILE" && (ulong)destination.Position < cpk.ContentOffset)
                            PadUntil(destination, cpk.ContentOffset);

                        string replacement = entry.FileType == "FILE"
                            ? SafeReplacementPath(replacementRoot, EntryPath(entry))
                            : null;
                        entry.FileOffset = (ulong)destination.Position;

                        if (replacement != null && File.Exists(replacement))
                        {
                            long newSize = new FileInfo(replacement).Length;
                            entry.FileSize = Convert.ChangeType(newSize, entry.FileSizeType, CultureInfo.InvariantCulture);
                            if (entry.ExtractSizeType != null)
                                entry.ExtractSize = Convert.ChangeType(newSize, entry.ExtractSizeType, CultureInfo.InvariantCulture);
                            cpk.UpdateFileEntry(entry);
                            using (var input = new FileStream(replacement, FileMode.Open, FileAccess.Read, FileShare.Read, CopyBufferSize, FileOptions.SequentialScan))
                            {
                                if (encryptReplacements) TransformJojo(input, destination, newSize);
                                else input.CopyTo(destination, CopyBufferSize);
                            }
                            replaced++;
                        }
                        else
                        {
                            cpk.UpdateFileEntry(entry);
                            ulong size = Convert.ToUInt64(entry.FileSize, CultureInfo.InvariantCulture);
                            CopyRange(source, destination, originalOffset, size);
                        }
                        Align(destination, (ulong)alignment);
                    }

                    cpk.WriteCPK(writer);
                    cpk.WriteITOC(writer);
                    cpk.WriteTOC(writer);
                    cpk.WriteETOC(writer);
                    cpk.WriteGTOC(writer);
                    writer.Flush();
                    destination.Flush(true);
                }

                Verify(tempPath);
                if (progress != null) progress(100, "Verified");
                if (File.Exists(outputPath)) File.Replace(tempPath, outputPath, outputPath + ".backup", true);
                else File.Move(tempPath, outputPath);
                Console.WriteLine("OK: rebuilt {0} replacement(s); verified {1}", replaced, outputPath);
            }
            finally
            {
                if (File.Exists(tempPath)) File.Delete(tempPath);
            }
        }

        private static void StandaloneBuild(string inputRoot, string outputPath, Action<int, string> progress)
        {
            inputRoot = Path.GetFullPath(inputRoot);
            if (!Directory.Exists(inputRoot)) throw new DirectoryNotFoundException(inputRoot);
            string profilePath = Path.Combine(Path.GetTempPath(), "CPKForge-data-" + Guid.NewGuid().ToString("N") + ".profile");
            try
            {
                using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("data-profile.cpk"))
                {
                    if (resource == null) throw new InvalidOperationException("Embedded data.cpk profile is missing.");
                    using (var file = new FileStream(profilePath, FileMode.CreateNew, FileAccess.Write, FileShare.None)) resource.CopyTo(file);
                }
                var profile = Open(profilePath);
                var missing = profile.FileTable.Where(e => e.FileType == "FILE")
                    .Select(EntryPath).Where(path => !File.Exists(SafeReplacementPath(inputRoot, path))).Take(10).ToList();
                if (missing.Count != 0)
                    throw new InvalidDataException("The input folder is incomplete. Missing: " + String.Join(", ", missing.ToArray()));
                Rebuild(profilePath, inputRoot, outputPath, progress, true);
            }
            finally
            {
                if (File.Exists(profilePath)) File.Delete(profilePath);
            }
        }

        private static void Unpack(string archivePath, string outputRoot, Action<int, string> progress)
        {
            archivePath = Path.GetFullPath(archivePath);
            outputRoot = Path.GetFullPath(outputRoot);
            Directory.CreateDirectory(outputRoot);
            var cpk = Open(archivePath);
            var entries = cpk.FileTable.Where(e => e.FileType == "FILE").ToList();
            using (var source = new FileStream(archivePath, FileMode.Open, FileAccess.Read, FileShare.Read, CopyBufferSize, FileOptions.SequentialScan))
            {
                for (int i = 0; i < entries.Count; i++)
                {
                    var entry = entries[i];
                    string relative = EntryPath(entry);
                    if (progress != null) progress(i * 100 / Math.Max(1, entries.Count), relative);
                    string destination = SafeReplacementPath(outputRoot, relative);
                    string parent = Path.GetDirectoryName(destination);
                    if (!String.IsNullOrEmpty(parent)) Directory.CreateDirectory(parent);
                    ulong storedSize = Convert.ToUInt64(entry.FileSize, CultureInfo.InvariantCulture);
                    source.Position = checked((long)entry.FileOffset);
                    bool encrypted = IsAsbrEncryptedArchive(archivePath);
                    string temporary = destination + ".extracting-" + Guid.NewGuid().ToString("N") + ".tmp";
                    try
                    {
                        byte[] packed = null;
                        if (encrypted || storedSize <= Int32.MaxValue)
                        {
                            if (storedSize > Int32.MaxValue) throw new InvalidDataException("Entry is too large: " + relative);
                            packed = new byte[(int)storedSize];
                            ReadExactly(source, packed);
                            if (encrypted) TransformJojo(packed);
                        }
                        bool compressed = packed != null && packed.Length >= 8 &&
                            System.Text.Encoding.ASCII.GetString(packed, 0, 8) == "CRILAYLA";
                        if (compressed)
                        {
                            int extractSize = Convert.ToInt32(entry.ExtractSize ?? entry.FileSize, CultureInfo.InvariantCulture);
                            byte[] unpacked = cpk.DecompressCRILAYLA(packed, extractSize);
                            File.WriteAllBytes(temporary, unpacked);
                        }
                        else if (packed != null)
                        {
                            File.WriteAllBytes(temporary, packed);
                        }
                        else
                        {
                            using (var destinationStream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None, CopyBufferSize, FileOptions.SequentialScan))
                                CopyRange(source, destinationStream, entry.FileOffset, storedSize);
                        }
                        if (File.Exists(destination)) File.Replace(temporary, destination, null, true);
                        else File.Move(temporary, destination);
                    }
                    finally
                    {
                        if (File.Exists(temporary)) File.Delete(temporary);
                    }
                }
            }
            if (progress != null) progress(100, "Complete");
        }

        private static void Inspect(string archivePath, string reportPath)
        {
            var cpk = Open(archivePath);
            var files = cpk.FileTable.Where(e => e.FileType == "FILE").ToList();
            var report = new System.Text.StringBuilder();
            report.AppendLine("Archive=" + Path.GetFullPath(archivePath));
            report.AppendLine("Length=" + new FileInfo(archivePath).Length);
            report.AppendLine("Entries=" + files.Count);
            report.AppendLine("TOC kinds=" + String.Join(",", files.Select(e => e.TOCName).Distinct().OrderBy(x => x).ToArray()));
            report.AppendLine("CPK packet=" + (cpk.CPK_packet == null ? 0 : cpk.CPK_packet.Length));
            report.AppendLine("TOC packet=" + (cpk.TOC_packet == null ? 0 : cpk.TOC_packet.Length));
            report.AppendLine("ITOC packet=" + (cpk.ITOC_packet == null ? 0 : cpk.ITOC_packet.Length));
            report.AppendLine("ETOC packet=" + (cpk.ETOC_packet == null ? 0 : cpk.ETOC_packet.Length));
            foreach (var pair in cpk.cpkdata.OrderBy(p => p.Key))
            {
                string value = pair.Value is byte[] ? "byte[" + ((byte[])pair.Value).Length + "]" : Convert.ToString(pair.Value, CultureInfo.InvariantCulture);
                report.AppendLine(pair.Key + "=" + value);
            }
            File.WriteAllText(reportPath, report.ToString());
        }

        private static void ReadExactly(Stream source, byte[] buffer)
        {
            int offset = 0;
            while (offset < buffer.Length)
            {
                int read = source.Read(buffer, offset, buffer.Length - offset);
                if (read == 0) throw new EndOfStreamException();
                offset += read;
            }
        }

        private static bool IsAsbrEncryptedArchive(string path)
        {
            string name = Path.GetFileName(path).ToLowerInvariant();
            return name != "adx2.cpk" && name != "movie.cpk" && name != "sound.cpk";
        }

        private static void TransformJojo(byte[] data)
        {
            using (var input = new MemoryStream(data, false))
            using (var output = new MemoryStream(data, true)) TransformJojo(input, output, data.LongLength);
        }

        private static void TransformJojo(Stream input, Stream output, long size)
        {
            Func<ulong, uint> u32 = value => (uint)(value & 0xffffffffUL);
            uint v1 = u32((ulong)size * 0x5F64UL + 0x5DEC219FUL);
            v1 = u32((ulong)(v1 / 32) ^ (ulong)u32((ulong)v1 * 0x1DA597UL));
            uint v2 = u32((ulong)(v1 / 32 + 0x85C9C2U) ^ (ulong)u32((ulong)v1 * 0x1DA597UL));
            uint v3 = u32((ulong)(v2 / 32 + 0x10B9384U) ^ (ulong)u32((ulong)v2 * 0x1DA597UL));
            uint v4 = u32((ulong)(v3 / 32 + 0x1915D46U) ^ (ulong)u32((ulong)v3 * 0x1DA597UL));
            byte[] buffer = new byte[CopyBufferSize];
            long remaining = size;
            while (remaining > 0)
            {
                int wanted = (int)Math.Min(buffer.Length, remaining);
                int read = input.Read(buffer, 0, wanted);
                if (read == 0) throw new EndOfStreamException();
                for (int pos = 0; pos < read; pos += 4)
                {
                    v1 = u32((ulong)u32((ulong)v1 * 2048UL) ^ v1);
                    uint v5 = u32((ulong)v4 ^ (ulong)(((v4 / 2048U) ^ v1) / 256U) ^ v1);
                    int take = Math.Min(4, read - pos);
                    for (int i = 0; i < take; i++) buffer[pos + i] ^= (byte)(v5 >> (8 * i));
                    v1 = v2; v2 = v3; v3 = v4; v4 = v5;
                }
                output.Write(buffer, 0, read);
                remaining -= read;
            }
        }

        private static void ComparePayloads(string firstPath, string secondPath)
        {
            var first = Open(firstPath).FileTable.Where(e => e.FileType == "FILE").ToDictionary(EntryPath, StringComparer.OrdinalIgnoreCase);
            var second = Open(secondPath).FileTable.Where(e => e.FileType == "FILE").ToDictionary(EntryPath, StringComparer.OrdinalIgnoreCase);
            if (first.Count != second.Count) throw new InvalidDataException("Archive file counts differ.");
            using (var a = File.OpenRead(firstPath))
            using (var b = File.OpenRead(secondPath))
            using (var sha = SHA256.Create())
            {
                foreach (var pair in first)
                {
                    FileEntry other;
                    if (!second.TryGetValue(pair.Key, out other)) throw new InvalidDataException("Missing entry: " + pair.Key);
                    ulong aSize = Convert.ToUInt64(pair.Value.FileSize, CultureInfo.InvariantCulture);
                    ulong bSize = Convert.ToUInt64(other.FileSize, CultureInfo.InvariantCulture);
                    if (aSize != bSize) throw new InvalidDataException("Size differs: " + pair.Key);
                    byte[] aHash = HashRange(sha, a, pair.Value.FileOffset, aSize);
                    byte[] bHash = HashRange(sha, b, other.FileOffset, bSize);
                    if (!aHash.SequenceEqual(bHash)) throw new InvalidDataException("Payload differs: " + pair.Key);
                }
            }
        }

        private static byte[] HashRange(HashAlgorithm hash, Stream stream, ulong offset, ulong count)
        {
            stream.Position = checked((long)offset);
            byte[] buffer = new byte[CopyBufferSize];
            hash.Initialize();
            while (count != 0)
            {
                int wanted = (int)Math.Min((ulong)buffer.Length, count);
                int read = stream.Read(buffer, 0, wanted);
                if (read == 0) throw new EndOfStreamException();
                hash.TransformBlock(buffer, 0, read, null, 0);
                count -= (ulong)read;
            }
            hash.TransformFinalBlock(new byte[0], 0, 0);
            return hash.Hash;
        }

        private static string EntryPath(FileEntry entry)
        {
            string dir = entry.DirName == null ? "" : entry.DirName.ToString();
            string name = entry.FileName == null ? "" : entry.FileName.ToString();
            return String.IsNullOrEmpty(dir) ? name : dir.TrimEnd('/', '\\') + "/" + name;
        }

        private static string SafeReplacementPath(string root, string relative)
        {
            string full = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar).TrimStart(Path.DirectorySeparatorChar)));
            string prefix = root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Unsafe archive path: " + relative);
            return full;
        }

        private static void CopyRange(Stream source, Stream destination, ulong offset, ulong count)
        {
            source.Position = checked((long)offset);
            byte[] buffer = new byte[CopyBufferSize];
            while (count != 0)
            {
                int wanted = (int)Math.Min((ulong)buffer.Length, count);
                int read = source.Read(buffer, 0, wanted);
                if (read == 0) throw new EndOfStreamException("Template ended while copying an entry.");
                destination.Write(buffer, 0, read);
                count -= (ulong)read;
            }
        }

        private static void PadUntil(Stream stream, ulong target)
        {
            while ((ulong)stream.Position < target) stream.WriteByte(0);
        }

        private static void Align(Stream stream, ulong boundary)
        {
            ulong position = (ulong)stream.Position;
            ulong target = ((position + boundary - 1) / boundary) * boundary;
            while ((ulong)stream.Position < target) stream.WriteByte(0);
        }

        private sealed class ForgeForm : Form
        {
            private readonly TextBox unpackArchive = new TextBox();
            private readonly TextBox unpackFolder = new TextBox();
            private readonly TextBox packFolder = new TextBox();
            private readonly TextBox packOutput = new TextBox();
            private readonly Button build = new Button();
            private readonly List<Button> actionButtons = new List<Button>();
            private readonly Label status = new Label();
            private readonly ProgressBar progressBar = new ProgressBar();

            public ForgeForm()
            {
                Text = "CPKForge";
                ClientSize = new Size(720, 330);
                MinimumSize = new Size(600, 365);
                StartPosition = FormStartPosition.CenterScreen;
                Font = new Font("Segoe UI", 9F);

                var tabs = new TabControl();
                tabs.SetBounds(10, 10, 700, 240);
                tabs.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
                tabs.DrawMode = TabDrawMode.OwnerDrawFixed;
                tabs.SizeMode = TabSizeMode.Fixed;
                tabs.ItemSize = new Size(130, 34);
                tabs.DrawItem += DrawTab;
                Controls.Add(tabs);

                var unpackTab = new TabPage("Unpack");
                var repackTab = new TabPage("Repack");
                tabs.TabPages.Add(unpackTab);
                tabs.TabPages.Add(repackTab);

                AddRow(unpackTab, "Input CPK", unpackArchive, 28, BrowseUnpackArchive);
                AddRow(unpackTab, "Output folder", unpackFolder, 76, BrowseUnpackFolder);

                var unpack = new Button { Text = "Unpack CPK" };
                unpack.SetBounds(130, 132, 140, 36);
                unpack.Click += StartUnpack;
                unpackTab.Controls.Add(unpack);
                actionButtons.Add(unpack);

                var verifyInput = new Button { Text = "Verify CPK" };
                verifyInput.SetBounds(282, 132, 120, 36);
                verifyInput.Click += StartVerifyInput;
                unpackTab.Controls.Add(verifyInput);
                actionButtons.Add(verifyInput);

                AddRow(repackTab, "Complete data folder", packFolder, 28, BrowsePackFolder);
                AddRow(repackTab, "Output CPK", packOutput, 76, BrowsePackOutput);

                build.Text = "Build and verify";
                build.SetBounds(130, 132, 150, 36);
                build.Click += StartBuild;
                repackTab.Controls.Add(build);
                actionButtons.Add(build);

                var verifyOutput = new Button { Text = "Verify output" };
                verifyOutput.SetBounds(292, 132, 120, 36);
                verifyOutput.Click += StartVerifyOutput;
                repackTab.Controls.Add(verifyOutput);
                actionButtons.Add(verifyOutput);

                progressBar.SetBounds(20, 265, 680, 20);
                progressBar.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
                Controls.Add(progressBar);

                status.Text = "Ready.";
                status.AutoEllipsis = true;
                status.SetBounds(20, 295, 680, 24);
                Controls.Add(status);

                ApplyDarkTheme(this);
            }

            private static readonly Color WindowColor = Color.FromArgb(18, 20, 24);
            private static readonly Color PanelColor = Color.FromArgb(27, 30, 36);
            private static readonly Color InputColor = Color.FromArgb(38, 42, 50);
            private static readonly Color AccentColor = Color.FromArgb(92, 124, 250);
            private static readonly Color TextColor = Color.FromArgb(235, 238, 245);
            private static readonly Color MutedColor = Color.FromArgb(165, 172, 186);

            private void ApplyDarkTheme(Control root)
            {
                if (root is Form || root is TabControl) root.BackColor = WindowColor;
                if (root is TabPage) root.BackColor = PanelColor;
                root.ForeColor = TextColor;
                foreach (Control control in root.Controls)
                {
                    control.ForeColor = TextColor;
                    if (control is TextBox)
                    {
                        control.BackColor = InputColor;
                        ((TextBox)control).BorderStyle = BorderStyle.FixedSingle;
                    }
                    else if (control is Button)
                    {
                        var button = (Button)control;
                        button.BackColor = AccentColor;
                        button.FlatStyle = FlatStyle.Flat;
                        button.FlatAppearance.BorderSize = 0;
                        button.Cursor = Cursors.Hand;
                    }
                    else if (control is Label)
                    {
                        control.BackColor = Color.Transparent;
                        if (control == status) control.ForeColor = MutedColor;
                    }
                    else if (control is TabPage)
                    {
                        control.BackColor = PanelColor;
                    }
                    if (control.HasChildren) ApplyDarkTheme(control);
                }
            }

            private void DrawTab(object sender, DrawItemEventArgs e)
            {
                var tabs = (TabControl)sender;
                bool selected = e.Index == tabs.SelectedIndex;
                using (var background = new SolidBrush(selected ? AccentColor : PanelColor))
                using (var foreground = new SolidBrush(TextColor))
                {
                    e.Graphics.FillRectangle(background, e.Bounds);
                    var format = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };
                    e.Graphics.DrawString(tabs.TabPages[e.Index].Text, Font, foreground, e.Bounds, format);
                }
            }

            private void AddRow(Control parent, string label, TextBox box, int y, EventHandler browse)
            {
                var caption = new Label { Text = label, TextAlign = ContentAlignment.MiddleRight };
                caption.SetBounds(10, y, 110, 28);
                box.SetBounds(130, y, 450, 28);
                box.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
                var button = new Button { Text = "Browse..." };
                button.SetBounds(590, y - 1, 80, 30);
                button.Anchor = AnchorStyles.Top | AnchorStyles.Right;
                button.Click += browse;
                parent.Controls.Add(caption);
                parent.Controls.Add(box);
                parent.Controls.Add(button);
            }

            private void BrowseUnpackArchive(object sender, EventArgs e)
            {
                using (var dialog = new OpenFileDialog { Filter = "CPK archives (*.cpk)|*.cpk|All files (*.*)|*.*" })
                    if (dialog.ShowDialog(this) == DialogResult.OK) unpackArchive.Text = dialog.FileName;
            }

            private void BrowseUnpackFolder(object sender, EventArgs e)
            {
                using (var dialog = new FolderBrowserDialog())
                    if (dialog.ShowDialog(this) == DialogResult.OK) unpackFolder.Text = dialog.SelectedPath;
            }

            private void BrowsePackFolder(object sender, EventArgs e)
            {
                using (var dialog = new FolderBrowserDialog())
                    if (dialog.ShowDialog(this) == DialogResult.OK) packFolder.Text = dialog.SelectedPath;
            }

            private void BrowsePackOutput(object sender, EventArgs e)
            {
                using (var dialog = new SaveFileDialog { Filter = "CPK archives (*.cpk)|*.cpk", AddExtension = true, DefaultExt = "cpk" })
                    if (dialog.ShowDialog(this) == DialogResult.OK) packOutput.Text = dialog.FileName;
            }

            private void StartBuild(object sender, EventArgs e)
            {
                RunWork(delegate { StandaloneBuild(packFolder.Text, packOutput.Text, ReportProgress); }, "Build completed and verified.");
            }

            private void StartUnpack(object sender, EventArgs e)
            {
                RunWork(delegate { Unpack(unpackArchive.Text, unpackFolder.Text, ReportProgress); }, "Archive unpacked successfully.");
            }

            private void ReportProgress(int percent, string item)
            {
                if (InvokeRequired) { BeginInvoke(new Action<int, string>(ReportProgress), percent, item); return; }
                progressBar.Value = Math.Max(0, Math.Min(100, percent));
                status.Text = percent + "%  " + item;
            }

            private void StartVerifyInput(object sender, EventArgs e)
            {
                RunWork(delegate { Verify(unpackArchive.Text); }, "Input archive is valid.");
            }

            private void StartVerifyOutput(object sender, EventArgs e)
            {
                RunWork(delegate { Verify(packOutput.Text); }, "Output archive is valid.");
            }

            private void RunWork(Action action, string success)
            {
                foreach (var button in actionButtons) button.Enabled = false;
                progressBar.Value = 0;
                status.Text = "Working...";
                var worker = new System.ComponentModel.BackgroundWorker();
                Exception failure = null;
                worker.DoWork += delegate { try { action(); } catch (Exception ex) { failure = ex; } };
                worker.RunWorkerCompleted += delegate
                {
                    foreach (var button in actionButtons) button.Enabled = true;
                    status.Text = failure == null ? success : "Failed: " + failure.Message;
                    MessageBox.Show(this, status.Text, failure == null ? "CPKForge" : "CPKForge error",
                        MessageBoxButtons.OK, failure == null ? MessageBoxIcon.Information : MessageBoxIcon.Error);
                };
                worker.RunWorkerAsync();
            }
        }
    }
}
