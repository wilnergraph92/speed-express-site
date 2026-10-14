# Speed Express Operations — impression Windows (appelé par impression.rs, jamais à la main).
# SES_ACTION = « lister » : une imprimante par ligne. SES_ACTION = « imprimer » : SES_DONNEES (base64) part TELLE QUELLE (RAW) vers
# SES_IMPRIMANTE par le spouleur Windows (winspool) — l'étiquette ZPL d'une imprimante thermique, sans pilote de mise en page.
# Les valeurs arrivent par l'environnement, jamais dans le texte du script : un nom d'imprimante ne peut rien y injecter.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if ($env:SES_ACTION -eq 'lister') {
  Get-CimInstance -ClassName Win32_Printer | ForEach-Object { $_.Name }
  exit 0
}
if ($env:SES_ACTION -ne 'imprimer') { throw "Action inconnue." }

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SesImpressionBrute {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public class DOCINFO {
    [MarshalAs(UnmanagedType.LPWStr)] public string pDocName;
    [MarshalAs(UnmanagedType.LPWStr)] public string pOutputFile;
    [MarshalAs(UnmanagedType.LPWStr)] public string pDataType;
  }
  [DllImport("winspool.drv", EntryPoint = "OpenPrinterW", SetLastError = true, CharSet = CharSet.Unicode)]
  static extern bool OpenPrinter(string nom, out IntPtr h, IntPtr defaut);
  [DllImport("winspool.drv", SetLastError = true)] static extern bool ClosePrinter(IntPtr h);
  [DllImport("winspool.drv", EntryPoint = "StartDocPrinterW", SetLastError = true, CharSet = CharSet.Unicode)]
  static extern int StartDocPrinter(IntPtr h, int niveau, [In, MarshalAs(UnmanagedType.LPStruct)] DOCINFO doc);
  [DllImport("winspool.drv", SetLastError = true)] static extern bool EndDocPrinter(IntPtr h);
  [DllImport("winspool.drv", SetLastError = true)] static extern bool StartPagePrinter(IntPtr h);
  [DllImport("winspool.drv", SetLastError = true)] static extern bool EndPagePrinter(IntPtr h);
  [DllImport("winspool.drv", SetLastError = true)] static extern bool WritePrinter(IntPtr h, byte[] octets, int n, out int ecrits);

  public static void Envoyer(string nom, byte[] octets) {
    IntPtr h;
    if (!OpenPrinter(nom, out h, IntPtr.Zero)) throw new Exception("OpenPrinter a échoué (" + Marshal.GetLastWin32Error() + ")");
    try {
      DOCINFO doc = new DOCINFO();
      doc.pDocName = "Etiquette Speed Express";
      doc.pDataType = "RAW";
      if (StartDocPrinter(h, 1, doc) == 0) throw new Exception("StartDocPrinter a échoué (" + Marshal.GetLastWin32Error() + ")");
      try {
        if (!StartPagePrinter(h)) throw new Exception("StartPagePrinter a échoué (" + Marshal.GetLastWin32Error() + ")");
        int ecrits;
        bool ok = WritePrinter(h, octets, octets.Length, out ecrits);
        EndPagePrinter(h);
        if (!ok || ecrits != octets.Length) throw new Exception("WritePrinter a échoué (" + Marshal.GetLastWin32Error() + ")");
      } finally { EndDocPrinter(h); }
    } finally { ClosePrinter(h); }
  }
}
'@

$octets = [Convert]::FromBase64String($env:SES_DONNEES)
[SesImpressionBrute]::Envoyer($env:SES_IMPRIMANTE, $octets)
