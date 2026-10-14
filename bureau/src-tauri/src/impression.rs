//! L'impression directe de l'étiquette 4 × 6 sur une imprimante thermique (ZPL), sans boîte de dialogue.
//!
//! macOS (et Linux) : CUPS, par `lpstat` pour la liste et `lp -o raw` pour l'envoi — les arguments passent séparément, jamais par
//! un interpréteur de commandes. Windows : le spouleur (winspool) en mode RAW, par un petit script PowerShell embarqué
//! (impression-windows.ps1) ; le nom de l'imprimante et les données lui arrivent par l'environnement, jamais dans le texte du
//! script. Dans les deux cas, l'appelant (lib.rs) ne passe qu'une imprimante que le système vient de déclarer.

use std::io::Write;
use std::process::{Command, Stdio};

#[cfg(target_os = "windows")]
const SCRIPT_WINDOWS: &str = include_str!("impression-windows.ps1");

#[cfg(target_os = "windows")]
fn powershell(action: &str, imprimante: &str, donnees: &[u8]) -> Result<String, String> {
    use base64::Engine;
    use std::os::windows::process::CommandExt;
    const SANS_FENETRE: u32 = 0x0800_0000; // CREATE_NO_WINDOW : pas de console qui clignote à chaque étiquette
    let mut enfant = Command::new("powershell.exe")
        .args(["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", "-"])
        .env("SES_ACTION", action)
        .env("SES_IMPRIMANTE", imprimante)
        .env("SES_DONNEES", base64::engine::general_purpose::STANDARD.encode(donnees))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .creation_flags(SANS_FENETRE)
        .spawn()
        .map_err(|e| format!("PowerShell indisponible : {e}"))?;
    enfant
        .stdin
        .take()
        .ok_or("PowerShell : entrée fermée")?
        .write_all(SCRIPT_WINDOWS.as_bytes())
        .map_err(|e| e.to_string())?;
    let sortie = enfant.wait_with_output().map_err(|e| e.to_string())?;
    if !sortie.status.success() {
        return Err(String::from_utf8_lossy(&sortie.stderr).trim().chars().take(400).collect());
    }
    Ok(String::from_utf8_lossy(&sortie.stdout).into_owned())
}

/// Les imprimantes installées sur ce poste, triées, sans doublon.
pub fn lister() -> Result<Vec<String>, String> {
    #[cfg(target_os = "windows")]
    let texte = powershell("lister", "", &[])?;
    #[cfg(not(target_os = "windows"))]
    let texte = {
        let sortie = Command::new("lpstat").arg("-e").output().map_err(|e| format!("lpstat indisponible : {e}"))?;
        // « lpstat -e » échoue quand aucune imprimante n'est installée : c'est une liste vide, pas une panne.
        String::from_utf8_lossy(&sortie.stdout).into_owned()
    };
    let mut noms: Vec<String> = texte
        .lines()
        .map(|l| l.trim().to_string())
        .filter(|l| !l.is_empty() && l.len() <= 200 && !l.chars().any(|c| c.is_control()))
        .collect();
    noms.sort();
    noms.dedup();
    Ok(noms)
}

/// Envoie les octets tels quels (ZPL) à l'imprimante nommée.
pub fn brut(imprimante: &str, donnees: &[u8]) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        powershell("imprimer", imprimante, donnees).map(|_| ())
    }
    #[cfg(not(target_os = "windows"))]
    {
        let mut enfant = Command::new("lp")
            .args(["-d", imprimante, "-o", "raw", "-t", "Etiquette Speed Express"])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("lp indisponible : {e}"))?;
        enfant.stdin.take().ok_or("lp : entrée fermée")?.write_all(donnees).map_err(|e| e.to_string())?;
        let sortie = enfant.wait_with_output().map_err(|e| e.to_string())?;
        if sortie.status.success() {
            Ok(())
        } else {
            Err(String::from_utf8_lossy(&sortie.stderr).trim().chars().take(400).collect())
        }
    }
}
