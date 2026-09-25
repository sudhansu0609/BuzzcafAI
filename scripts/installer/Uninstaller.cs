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

            DialogResult res = MessageBox.Show(
                "Are you sure you want to uninstall Buzzcaf Studio?\n\nThis will remove shortcuts and unregister the application from Windows.",
                "Uninstall Buzzcaf Studio",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question
            );

            if (res != DialogResult.Yes) return;

            string appDir = AppDomain.CurrentDomain.BaseDirectory;

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

            MessageBox.Show(
                "Buzzcaf Studio was successfully removed from your computer.",
                "Uninstall Complete",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information
            );
        }
    }
}
