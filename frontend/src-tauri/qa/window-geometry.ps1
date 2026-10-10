param([int]$ProcessIdToCheck)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class YanceQaWindow {
 [StructLayout(LayoutKind.Sequential)]
 public struct RECT { public int left, top, right, bottom; }
 [DllImport("user32.dll")]
 public static extern bool GetWindowRect(IntPtr handle, out RECT rect);
}
'@
$process = Get-Process -Id $ProcessIdToCheck -ErrorAction Stop
$handle = $process.MainWindowHandle
if($handle -eq [IntPtr]::Zero) { throw 'NO_NATIVE_WINDOW' }
$rectangle = New-Object YanceQaWindow+RECT
if(-not [YanceQaWindow]::GetWindowRect($handle, [ref]$rectangle)) { throw 'GET_WINDOW_RECT_FAILED' }
"PROCESS_RUNNING=$(-not $process.HasExited)"
"WINDOW_RESPONSIVE=$($process.Responding)"
"WINDOW_WIDTH=$($rectangle.right-$rectangle.left)"
"WINDOW_HEIGHT=$($rectangle.bottom-$rectangle.top)"
"WINDOW_CLASSIC_HANDLE_PRESENT=True"
