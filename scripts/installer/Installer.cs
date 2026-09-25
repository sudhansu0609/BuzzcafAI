using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("Buzzcaf Studio Setup")]
[assembly: AssemblyDescription("Buzzcaf Media AI Studio Desktop Installer")]
[assembly: AssemblyCompany("Buzzcaf Media")]
[assembly: AssemblyProduct("Buzzcaf Studio Setup")]
[assembly: AssemblyCopyright("Copyright © Buzzcaf Media 2026")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace BuzzcafStudio.Installer
{
    static class Program
    {
        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [STAThread]
        static void Main()
        {
            try { SetProcessDPIAware(); } catch { }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new InstallerForm());
        }
    }

    public class InstallerForm : Form
    {
        private TextBox txtInstallDir;
        private CheckBox chkDesktop;
        private CheckBox chkStartMenu;
        private CheckBox chkRegister;
        private CheckBox chkLaunch;
        private Button btnInstall;
        private Button btnCancel;
        private Button btnBrowse;
        private ProgressBar progressBar;
        private Label lblStatus;
        private string sourceDir;

        public InstallerForm()
        {
            sourceDir = FindSourceDir();
            InitializeComponent();
        }

        private string FindSourceDir()
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            if (File.Exists(Path.Combine(baseDir, "Buzzcaf Studio.exe"))) return baseDir;

            DirectoryInfo parent = Directory.GetParent(baseDir);
            if (parent != null && File.Exists(Path.Combine(parent.FullName, "Buzzcaf Studio.exe")))
            {
                return parent.FullName;
            }

            string cwd = Directory.GetCurrentDirectory();
            if (File.Exists(Path.Combine(cwd, "Buzzcaf Studio.exe"))) return cwd;

            return baseDir;
        }

        private void InitializeComponent()
        {
            this.Text = "Buzzcaf Studio Setup";
            this.Size = new Size(580, 480);
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.StartPosition = FormStartPosition.CenterScreen;
            this.BackColor = Color.FromArgb(18, 20, 29);
            this.ForeColor = Color.FromArgb(241, 245, 249);
            this.Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);

            string iconPath = Path.Combine(sourceDir, "assets", "buzzcaf_studio.ico");
            if (File.Exists(iconPath))
            {
                try { this.Icon = new Icon(iconPath); } catch { }
            }

            // Header Panel
            Panel pnlHeader = new Panel
            {
                Dock = DockStyle.Top,
                Height = 85,
                BackColor = Color.FromArgb(30, 27, 75)
            };

            Label lblTitle = new Label
            {
                Text = "Buzzcaf Studio Setup",
                Font = new Font("Segoe UI", 13.5f, FontStyle.Bold),
                ForeColor = Color.White,
                Location = new Point(24, 18),
                AutoSize = true
            };

            Label lblSubtitle = new Label
            {
                Text = "Install Buzzcaf Media AI Studio Desktop on your computer",
                Font = new Font("Segoe UI", 9f, FontStyle.Regular),
                ForeColor = Color.FromArgb(167, 139, 250),
                Location = new Point(25, 48),
                AutoSize = true
            };

            pnlHeader.Controls.Add(lblTitle);
            pnlHeader.Controls.Add(lblSubtitle);
            this.Controls.Add(pnlHeader);

            // Body Panel
            Panel pnlBody = new Panel
            {
                Location = new Point(24, 100),
                Size = new Size(520, 270)
            };

            Label lblDirPrompt = new Label
            {
                Text = "Installation Location:",
                Location = new Point(0, 10),
                AutoSize = true,
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold)
            };

            string defaultPath = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs",
                "Buzzcaf Studio"
            );

            // If running directly from checkout, give user the choice or default
            txtInstallDir = new TextBox
            {
                Text = sourceDir,
                Location = new Point(0, 35),
                Size = new Size(410, 26),
                BackColor = Color.FromArgb(15, 23, 42),
                ForeColor = Color.White,
                BorderStyle = BorderStyle.FixedSingle
            };

            btnBrowse = new Button
            {
                Text = "Browse…",
                Location = new Point(420, 34),
                Size = new Size(95, 28),
                BackColor = Color.FromArgb(51, 65, 85),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            btnBrowse.Click += (s, e) =>
            {
                using (FolderBrowserDialog fbd = new FolderBrowserDialog())
                {
                    fbd.SelectedPath = txtInstallDir.Text;
                    if (fbd.ShowDialog() == DialogResult.OK)
                    {
                        txtInstallDir.Text = fbd.SelectedPath;
                    }
                }
            };

            Label lblOptions = new Label
            {
                Text = "Shortcuts and Options:",
                Location = new Point(0, 78),
                AutoSize = true,
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold)
            };

            chkDesktop = new CheckBox
            {
                Text = "Create Desktop shortcut (Buzzcaf Studio)",
                Checked = true,
                Location = new Point(5, 105),
                AutoSize = true
            };

            chkStartMenu = new CheckBox
            {
                Text = "Create Start Menu shortcut (Buzzcaf Media > Buzzcaf Studio)",
                Checked = true,
                Location = new Point(5, 133),
                AutoSize = true
            };

            chkRegister = new CheckBox
            {
                Text = "Register in Windows Installed Apps & Add to Run/Search (Win+R: buzzcaf)",
                Checked = true,
                Location = new Point(5, 161),
                AutoSize = true
            };

            chkLaunch = new CheckBox
            {
                Text = "Launch Buzzcaf Studio after installation",
                Checked = true,
                Location = new Point(5, 189),
                AutoSize = true
            };

            progressBar = new ProgressBar
            {
                Location = new Point(0, 225),
                Size = new Size(515, 18),
                Visible = false
            };

            lblStatus = new Label
            {
                Location = new Point(0, 248),
                Size = new Size(515, 20),
                Text = "",
                ForeColor = Color.FromArgb(74, 222, 128),
                Visible = false
            };

            pnlBody.Controls.Add(lblDirPrompt);
            pnlBody.Controls.Add(txtInstallDir);
            pnlBody.Controls.Add(btnBrowse);
            pnlBody.Controls.Add(lblOptions);
            pnlBody.Controls.Add(chkDesktop);
            pnlBody.Controls.Add(chkStartMenu);
            pnlBody.Controls.Add(chkRegister);
            pnlBody.Controls.Add(chkLaunch);
            pnlBody.Controls.Add(progressBar);
            pnlBody.Controls.Add(lblStatus);
            this.Controls.Add(pnlBody);

            // Footer Panel
            Panel pnlFooter = new Panel
            {
                Dock = DockStyle.Bottom,
                Height = 65,
                BackColor = Color.FromArgb(15, 17, 26)
            };

            btnCancel = new Button
            {
                Text = "Cancel",
                Location = new Point(320, 16),
                Size = new Size(95, 32),
                BackColor = Color.FromArgb(30, 41, 59),
                ForeColor = Color.FromArgb(203, 213, 225),
                FlatStyle = FlatStyle.Flat
            };
            btnCancel.Click += (s, e) => this.Close();

            btnInstall = new Button
            {
                Text = "Install Now",
                Location = new Point(425, 16),
                Size = new Size(115, 32),
                BackColor = Color.FromArgb(124, 58, 237),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold)
            };
            btnInstall.Click += BtnInstall_Click;

            pnlFooter.Controls.Add(btnCancel);
            pnlFooter.Controls.Add(btnInstall);
            this.Controls.Add(pnlFooter);
        }

        private void BtnInstall_Click(object sender, EventArgs e)
        {
            string targetDir = txtInstallDir.Text.Trim();
            if (string.IsNullOrEmpty(targetDir))
            {
                MessageBox.Show("Please specify a valid installation directory.", "Invalid Path", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            btnInstall.Enabled = false;
            btnCancel.Enabled = false;
            btnBrowse.Enabled = false;
            progressBar.Visible = true;
            progressBar.Style = ProgressBarStyle.Marquee;
            lblStatus.Visible = true;
            lblStatus.Text = "Configuring Buzzcaf Studio installation…";

            Thread worker = new Thread(() =>
            {
                try
                {
                    PerformInstall(targetDir);
                    this.Invoke(new Action(() =>
                    {
                        progressBar.Style = ProgressBarStyle.Continuous;
                        progressBar.Value = 100;
                        lblStatus.Text = "✓ Installation completed successfully!";
                        btnInstall.Text = "Close";
                        btnInstall.Enabled = true;
                        btnInstall.Click -= BtnInstall_Click;
                        btnInstall.Click += (s, ev) => this.Close();

                        if (chkLaunch.Checked)
                        {
                            string exePath = Path.Combine(targetDir, "Buzzcaf Studio.exe");
                            if (File.Exists(exePath))
                            {
                                Process.Start(new ProcessStartInfo
                                {
                                    FileName = exePath,
                                    WorkingDirectory = targetDir
                                });
                            }
                        }
                    }));
                }
                catch (Exception ex)
                {
                    this.Invoke(new Action(() =>
                    {
                        progressBar.Visible = false;
                        lblStatus.ForeColor = Color.FromArgb(248, 113, 113);
                        lblStatus.Text = "Installation error: " + ex.Message;
                        btnInstall.Enabled = true;
                        btnCancel.Enabled = true;
                    }));
                }
            });
            worker.IsBackground = true;
            worker.Start();
        }

        private void PerformInstall(string targetDir)
        {
            Directory.CreateDirectory(targetDir);

            // Copy files if target directory is different from source
            string normalizedSource = Path.GetFullPath(sourceDir).TrimEnd('\\');
            string normalizedTarget = Path.GetFullPath(targetDir).TrimEnd('\\');

            if (!string.Equals(normalizedSource, normalizedTarget, StringComparison.OrdinalIgnoreCase))
            {
                CopyDirectory(sourceDir, targetDir);
            }

            string appExe = Path.Combine(targetDir, "Buzzcaf Studio.exe");
            string iconPath = Path.Combine(targetDir, "assets", "buzzcaf_studio.ico");

            // Compile Uninstaller into targetDir
            string uninstallerExe = Path.Combine(targetDir, "Uninstall Buzzcaf Studio.exe");
            BuildUninstaller(uninstallerExe, targetDir);

            // Create Desktop Shortcut
            if (chkDesktop.Checked && File.Exists(appExe))
            {
                string desktopFolder = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                string lnkPath = Path.Combine(desktopFolder, "Buzzcaf Studio.lnk");
                CreateShortcut(lnkPath, appExe, targetDir, iconPath, "Buzzcaf Studio - AI Media Studio");
            }

            // Create Start Menu Shortcut
            if (chkStartMenu.Checked && File.Exists(appExe))
            {
                string programsFolder = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
                string buzzcafStartMenu = Path.Combine(programsFolder, "Buzzcaf Media");
                Directory.CreateDirectory(buzzcafStartMenu);
                string lnkPath = Path.Combine(buzzcafStartMenu, "Buzzcaf Studio.lnk");
                CreateShortcut(lnkPath, appExe, targetDir, iconPath, "Buzzcaf Studio - AI Media Studio");

                if (File.Exists(uninstallerExe))
                {
                    string uninstLnk = Path.Combine(buzzcafStartMenu, "Uninstall Buzzcaf Studio.lnk");
                    CreateShortcut(uninstLnk, uninstallerExe, targetDir, iconPath, "Uninstall Buzzcaf Studio");
                }
            }

            // Register in Registry
            if (chkRegister.Checked)
            {
                RegisterInWindows(targetDir, appExe, iconPath, uninstallerExe);
            }
        }

        private void CopyDirectory(string source, string destination)
        {
            Directory.CreateDirectory(destination);

            foreach (string file in Directory.GetFiles(source))
            {
                string name = Path.GetFileName(file);
                // Skip git and temp folders
                if (name.StartsWith(".git") || name.EndsWith(".tmp")) continue;
                string destFile = Path.Combine(destination, name);
                File.Copy(file, destFile, true);
            }

            foreach (string dir in Directory.GetDirectories(source))
            {
                string name = Path.GetFileName(dir);
                if (name == ".git" || name == ".pytest_cache" || name == "__pycache__" || name == "node_modules") continue;
                string destSubDir = Path.Combine(destination, name);
                CopyDirectory(dir, destSubDir);
            }
        }

        private void CreateShortcut(string shortcutPath, string targetExe, string workingDir, string iconPath, string description)
        {
            try
            {
                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType == null) return;
                object shell = Activator.CreateInstance(shellType);
                object shortcut = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { shortcutPath });

                Type shortcutType = shortcut.GetType();
                shortcutType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { targetExe });
                shortcutType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { workingDir });
                shortcutType.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { description });
                if (File.Exists(iconPath))
                {
                    shortcutType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { iconPath + ",0" });
                }
                shortcutType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
            }
            catch { }
        }

        private void RegisterInWindows(string targetDir, string appExe, string iconPath, string uninstallerExe)
        {
            try
            {
                // 1. Windows Installed Apps (Add/Remove Programs)
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\BuzzcafStudio"))
                {
                    if (key != null)
                    {
                        key.SetValue("DisplayName", "Buzzcaf Studio");
                        key.SetValue("DisplayVersion", "1.0.0");
                        key.SetValue("Publisher", "Buzzcaf Media");
                        key.SetValue("DisplayIcon", File.Exists(iconPath) ? iconPath : appExe);
                        key.SetValue("InstallLocation", targetDir);
                        key.SetValue("UninstallString", "\"" + uninstallerExe + "\"");
                        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                        key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                        key.SetValue("EstimatedSize", 120000, RegistryValueKind.DWord);
                    }
                }

                // 2. Windows App Paths (Win+R: buzzcaf or buzzcaf_studio)
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\App Paths\buzzcaf.exe"))
                {
                    if (key != null)
                    {
                        key.SetValue("", appExe);
                        key.SetValue("Path", targetDir);
                    }
                }
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\App Paths\buzzcaf_studio.exe"))
                {
                    if (key != null)
                    {
                        key.SetValue("", appExe);
                        key.SetValue("Path", targetDir);
                    }
                }
            }
            catch { }
        }

        private void BuildUninstaller(string uninstallerExe, string targetDir)
        {
            string uninstSource = Path.Combine(sourceDir, "scripts", "installer", "Uninstaller.cs");
            if (!File.Exists(uninstSource)) return;

            string cscPath = @"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe";
            if (!File.Exists(cscPath)) return;

            string iconArg = "";
            string iconPath = Path.Combine(sourceDir, "assets", "buzzcaf_studio.ico");
            if (File.Exists(iconPath))
            {
                iconArg = " /win32icon:\"" + iconPath + "\"";
            }

            ProcessStartInfo psi = new ProcessStartInfo
            {
                FileName = cscPath,
                Arguments = "/target:winexe /out:\"" + uninstallerExe + "\"" + iconArg + " /r:System.dll,System.Windows.Forms.dll,System.Drawing.dll \"" + uninstSource + "\"",
                UseShellExecute = false,
                CreateNoWindow = true
            };

            try
            {
                Process proc = Process.Start(psi);
                proc.WaitForExit();
            }
            catch { }
        }
    }
}
