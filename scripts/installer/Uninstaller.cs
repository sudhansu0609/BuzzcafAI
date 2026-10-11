using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("Uninstall Buzzcaf Studio")]
[assembly: AssemblyDescription("Buzzcaf Media AI Studio Desktop Uninstaller")]
[assembly: AssemblyCompany("Buzzcaf Media")]
[assembly: AssemblyProduct("Buzzcaf Studio")]
[assembly: AssemblyCopyright("Copyright © Buzzcaf Media 2026")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace BuzzcafStudio.Uninstaller
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
            Application.Run(new UninstallForm());
        }
    }

    public class UninstallForm : Form
    {
        private Label lblMessage;
        private Button btnUninstall;
        private Button btnCancel;
        private bool done;

        public UninstallForm()
        {
            this.Text = "Uninstall Buzzcaf Studio";
            this.Size = new Size(520, 330);
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.MinimizeBox = false;
            this.StartPosition = FormStartPosition.CenterScreen;
            this.BackColor = Color.FromArgb(18, 20, 29);
            this.ForeColor = Color.FromArgb(241, 245, 249);
            this.Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);

            // The window / taskbar icon is the one compiled into this exe.
            try { this.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            Panel pnlHeader = new Panel
            {
                Dock = DockStyle.Top,
                Height = 85,
                BackColor = Color.FromArgb(14, 16, 23)
            };

            Image logo = LoadLogo();
            if (logo != null)
            {
                pnlHeader.Controls.Add(new PictureBox
                {
                    Image = logo,
                    SizeMode = PictureBoxSizeMode.Zoom,
                    Location = new Point(22, 12),
                    Size = new Size(194, 60),
                    BackColor = Color.Transparent
                });
            }

            pnlHeader.Controls.Add(new Label
            {
                Text = "Uninstall",
                Font = new Font("Segoe UI", 13.5f, FontStyle.Bold),
                ForeColor = Color.White,
                Location = new Point(250, 28),
                AutoSize = true
            });
            pnlHeader.Controls.Add(new Panel
            {
                Dock = DockStyle.Bottom,
                Height = 3,
                BackColor = Color.FromArgb(249, 115, 22)
            });
            this.Controls.Add(pnlHeader);

            lblMessage = new Label
            {
                Text = "Are you sure you want to uninstall Buzzcaf Studio?\n\nThis will remove shortcuts and unregister the application from Windows.",
                Location = new Point(24, 108),
                Size = new Size(465, 90),
                ForeColor = Color.FromArgb(241, 245, 249)
            };
            this.Controls.Add(lblMessage);

            Panel pnlFooter = new Panel
            {
                Dock = DockStyle.Bottom,
                Height = 65,
                BackColor = Color.FromArgb(15, 17, 26)
            };

            btnCancel = new Button
            {
                Text = "Cancel",
                Location = new Point(285, 16),
                Size = new Size(95, 32),
                BackColor = Color.FromArgb(30, 41, 59),
                ForeColor = Color.FromArgb(203, 213, 225),
                FlatStyle = FlatStyle.Flat
            };
            btnCancel.Click += (s, e) => this.Close();

            btnUninstall = new Button
            {
                Text = "Uninstall",
                Location = new Point(390, 16),
                Size = new Size(100, 32),
                BackColor = Color.FromArgb(234, 88, 12),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold)
            };
            btnUninstall.Click += (s, e) =>
            {
                if (done)
                {
                    this.Close();
                    return;
                }
                RemoveEverything();
                done = true;
                lblMessage.Text = "Buzzcaf Studio was successfully removed from your computer.";
                lblMessage.ForeColor = Color.FromArgb(74, 222, 128);
                this.Text = "Uninstall Complete";
                btnCancel.Visible = false;
                btnUninstall.Text = "Close";
            };

            pnlFooter.Controls.Add(btnCancel);
            pnlFooter.Controls.Add(btnUninstall);
            this.Controls.Add(pnlFooter);
        }

        // The logo PNG is compiled into the exe (scripts/build_windows_app.py).
        private static Image LoadLogo()
        {
            try
            {
                using (Stream st = Assembly.GetExecutingAssembly().GetManifestResourceStream("BuzzcafStudio.logo-dark.png"))
                {
                    if (st == null) return null;
                    return new Bitmap(st);
                }
            }
            catch { return null; }
        }

        private void RemoveEverything()
        {
            // 1. Remove Desktop Shortcut
            try
            {
                string desktopLnk = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                    "Buzzcaf Studio.lnk"
                );
                if (File.Exists(desktopLnk)) File.Delete(desktopLnk);
            }
            catch { }

            // 2. Remove Start Menu Shortcut
            try
            {
                string buzzcafStartMenu = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.Programs),
                    "Buzzcaf Media"
                );
                if (Directory.Exists(buzzcafStartMenu))
                {
                    Directory.Delete(buzzcafStartMenu, true);
                }
            }
            catch { }

            // 3. Remove Registry Entries
            try
            {
                Registry.CurrentUser.DeleteSubKeyTree(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\BuzzcafStudio", false);
                Registry.CurrentUser.DeleteSubKeyTree(@"Software\Microsoft\Windows\CurrentVersion\App Paths\buzzcaf.exe", false);
                Registry.CurrentUser.DeleteSubKeyTree(@"Software\Microsoft\Windows\CurrentVersion\App Paths\buzzcaf_studio.exe", false);
            }
            catch { }
        }
    }
}
