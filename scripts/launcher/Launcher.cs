using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("Buzzcaf Studio")]
[assembly: AssemblyDescription("Buzzcaf Media AI Studio Desktop Application")]
[assembly: AssemblyCompany("Buzzcaf Media")]
[assembly: AssemblyProduct("Buzzcaf Studio")]
[assembly: AssemblyCopyright("Copyright © Buzzcaf Media 2026")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace BuzzcafStudio.Launcher
{
    static class Program
    {
        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(IntPtr hJob, int JobObjectInfoClass, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr hObject);

        private const int JobObjectExtendedLimitInformation = 9;
        private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IO_COUNTERS
        {
            public ulong ReadOperationCount;
            public ulong WriteOperationCount;
            public ulong OtherOperationCount;
            public ulong ReadTransferCount;
            public ulong WriteTransferCount;
            public ulong OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryLimit;
            public UIntPtr PeakJobMemoryLimit;
        }

        [STAThread]
        static void Main(string[] args)
        {
            try
            {
                SetProcessDPIAware();
            }
            catch { }

            string rootDir = FindProjectRoot();
            if (string.IsNullOrEmpty(rootDir))
            {
                MessageBox.Show(
                    "Could not find Buzzcaf Studio installation directory.\n" +
                    "Please make sure Buzzcaf Studio.exe is in the project folder.",
                    "Buzzcaf Studio Error",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return;
            }

            string pythonExe = FindPython(rootDir);
            if (string.IsNullOrEmpty(pythonExe))
            {
                MessageBox.Show(
                    "Python was not found on your system.\n\n" +
                    "Buzzcaf Studio requires Python 3.10 or higher.\n" +
                    "Please install Python (https://www.python.org) or set up the virtual environment in .venv.",
                    "Buzzcaf Studio - Python Required",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning
                );
                return;
            }

            string backendScript = Path.Combine(rootDir, "backend", "desktop_app.py");
            if (!File.Exists(backendScript))
            {
                MessageBox.Show(
                    "Desktop application script not found at:\n" + backendScript,
                    "Buzzcaf Studio Error",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return;
            }

            // Ghost Process Guard: If port 8099 is locked by a dead/unresponsive process, clear it.
            CheckAndCleanOrphanPort(8099);

            // Forward user arguments (e.g. --dev, --devtools)
            StringBuilder argBuilder = new StringBuilder();
            argBuilder.Append("-X utf8 \"").Append(backendScript).Append("\"");
            foreach (string arg in args)
            {
                argBuilder.Append(" ").Append(QuoteArg(arg));
            }

            ProcessStartInfo psi = new ProcessStartInfo
            {
                FileName = pythonExe,
                Arguments = argBuilder.ToString(),
                WorkingDirectory = Path.Combine(rootDir, "backend"),
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };

            // Ensure UTF-8 output encoding
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            psi.EnvironmentVariables["BUZZCAF_ROOT"] = rootDir;

            // Create a Job Object so closing the main app cleanly terminates child Python and Node processes
            IntPtr jobHandle = CreateJobObject(IntPtr.Zero, null);
            if (jobHandle != IntPtr.Zero)
            {
                JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

                int length = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
                IntPtr infoPtr = Marshal.AllocHGlobal(length);
                try
                {
                    Marshal.StructureToPtr(info, infoPtr, false);
                    SetInformationJobObject(jobHandle, JobObjectExtendedLimitInformation, infoPtr, (uint)length);
                }
                finally
                {
                    Marshal.FreeHGlobal(infoPtr);
                }
            }

            try
            {
                Process proc = Process.Start(psi);
                if (proc != null)
                {
                    if (jobHandle != IntPtr.Zero)
                    {
                        try
                        {
                            AssignProcessToJobObject(jobHandle, proc.Handle);
                        }
                        catch { }
                    }

                    // Keep launcher alive until Studio window closes
                    proc.WaitForExit();
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    "Failed to start Buzzcaf Studio:\n" + ex.Message,
                    "Buzzcaf Studio Error",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
            }
            finally
            {
                if (jobHandle != IntPtr.Zero)
                {
                    CloseHandle(jobHandle);
                }
            }
        }

        private static string QuoteArg(string arg)
        {
            if (string.IsNullOrEmpty(arg)) return "\"\"";
            if (!arg.Contains(" ") && !arg.Contains("\"")) return arg;
            return "\"" + arg.Replace("\"", "\\\"") + "\"";
        }

        private static string FindProjectRoot()
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            if (File.Exists(Path.Combine(baseDir, "backend", "desktop_app.py")))
            {
                return baseDir;
            }

            DirectoryInfo parentInfo = Directory.GetParent(baseDir);
            string parent = parentInfo != null ? parentInfo.FullName : null;
            if (!string.IsNullOrEmpty(parent) && File.Exists(Path.Combine(parent, "backend", "desktop_app.py")))
            {
                return parent;
            }

            string cwd = Directory.GetCurrentDirectory();
            if (File.Exists(Path.Combine(cwd, "backend", "desktop_app.py")))
            {
                return cwd;
            }

            return null;
        }

        private static string FindPython(string rootDir)
        {
            string envPy = Environment.GetEnvironmentVariable("BUZZCAF_PYTHON");
            if (!string.IsNullOrEmpty(envPy) && File.Exists(envPy))
            {
                return envPy;
            }

            string[] venvCandidates = new[]
            {
                Path.Combine(rootDir, ".venv", "Scripts", "pythonw.exe"),
                Path.Combine(rootDir, ".venv", "Scripts", "python.exe"),
                Path.Combine(rootDir, "venv", "Scripts", "pythonw.exe"),
                Path.Combine(rootDir, "venv", "Scripts", "python.exe")
            };

            foreach (string candidate in venvCandidates)
            {
                if (File.Exists(candidate)) return candidate;
            }

            // Search PATH
            string pathEnv = Environment.GetEnvironmentVariable("PATH") ?? "";
            string[] dirs = pathEnv.Split(Path.PathSeparator);
            foreach (string dir in dirs)
            {
                try
                {
                    string pw = Path.Combine(dir.Trim(), "pythonw.exe");
                    if (File.Exists(pw)) return pw;
                }
                catch { }
            }
            foreach (string dir in dirs)
            {
                try
                {
                    string py = Path.Combine(dir.Trim(), "python.exe");
                    if (File.Exists(py)) return py;
                }
                catch { }
            }

            // Standard Windows install locations
            string[] standardLocations = new[]
            {
                @"C:\Python314\pythonw.exe",
                @"C:\Python313\pythonw.exe",
                @"C:\Python312\pythonw.exe",
                @"C:\Python311\pythonw.exe",
                @"C:\Python310\pythonw.exe",
                @"C:\Python314\python.exe",
                @"C:\Python313\python.exe",
                @"C:\Python312\python.exe",
                @"C:\Python311\python.exe",
                @"C:\Python310\python.exe",
            };

            foreach (string loc in standardLocations)
            {
                if (File.Exists(loc)) return loc;
            }

            // User local app data python
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string pyPrograms = Path.Combine(localAppData, "Programs", "Python");
            if (Directory.Exists(pyPrograms))
            {
                try
                {
                    var dirsInPy = Directory.GetDirectories(pyPrograms, "Python3*");
                    foreach (var d in dirsInPy.OrderByDescending(x => x))
                    {
                        string pw = Path.Combine(d, "pythonw.exe");
                        if (File.Exists(pw)) return pw;
                        string py = Path.Combine(d, "python.exe");
                        if (File.Exists(py)) return py;
                    }
                }
                catch { }
            }

            return null;
        }

        private static void CheckAndCleanOrphanPort(int port)
        {
            try
            {
                // Check if port is listening
                using (TcpClient tcp = new TcpClient())
                {
                    IAsyncResult ar = tcp.BeginConnect("127.0.0.1", port, null, null);
                    bool connected = ar.AsyncWaitHandle.WaitOne(200);
                    if (!connected) return; // Port is free!
                }

                // Port is connected: verify if an active Buzzcaf Studio WebView is open
                bool hasActiveStudioWindow = false;
                foreach (Process p in Process.GetProcesses())
                {
                    try
                    {
                        if (p.MainWindowHandle != IntPtr.Zero &&
                            (p.MainWindowTitle.Contains("Buzzcaf Studio") || p.ProcessName.ToLower().Contains("buzzcaf")))
                        {
                            hasActiveStudioWindow = true;
                            break;
                        }
                    }
                    catch { }
                }

                // If no active Studio window is visible, this is an orphaned zombie backend process holding the port.
                if (!hasActiveStudioWindow)
                {
                    // Find process holding port via netstat and kill it
                    Process netstat = new Process
                    {
                        StartInfo = new ProcessStartInfo
                        {
                            FileName = "netstat.exe",
                            Arguments = "-ano -p tcp",
                            UseShellExecute = false,
                            RedirectStandardOutput = true,
                            CreateNoWindow = true
                        }
                    };
                    netstat.Start();
                    string output = netstat.StandardOutput.ReadToEnd();
                    netstat.WaitForExit();

                    string[] lines = output.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
                    foreach (string line in lines)
                    {
                        if (line.Contains(":" + port) && line.ToUpper().Contains("LISTENING"))
                        {
                            string[] parts = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                            if (parts.Length >= 5)
                            {
                                string pidStr = parts[parts.Length - 1];
                                int pid;
                                if (int.TryParse(pidStr, out pid) && pid > 0)
                                {
                                    try
                                    {
                                        Process orphan = Process.GetProcessById(pid);
                                        // Only kill if python / pythonw / node
                                        string pName = orphan.ProcessName.ToLower();
                                        if (pName.Contains("python") || pName.Contains("node"))
                                        {
                                            orphan.Kill();
                                        }
                                    }
                                    catch { }
                                }
                            }
                        }
                    }
                }
            }
            catch { }
        }
    }
}
