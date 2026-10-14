//! Les mises à jour : signées, vérifiées avant installation, sur deux canaux.
//!
//! Chaque canal a son manifeste « latest.json » publié dans une version GitHub fixe du dépôt du site
//! (bureau-canal-stable, bureau-canal-beta), mise à jour par .github/workflows/bureau.yml. Le module de Tauri refuse toute mise à
//! jour dont la signature ne correspond pas à la clé PUBLIQUE embarquée (plugins.updater.pubkey, posée par le workflow à la
//! construction). Tant qu'aucune clé n'est posée, les mises à jour sont simplement « pas encore activées » : rien ne s'installe.

use serde_json::{json, Value};
use tauri::{AppHandle, Url};
use tauri_plugin_updater::UpdaterExt;

const DEPOT: &str = "https://github.com/wilnergraph92/speed-express-site/releases/download";

fn cle_publique(app: &AppHandle) -> Option<String> {
    app.config()
        .plugins
        .0
        .get("updater")
        .and_then(|u| u.get("pubkey"))
        .and_then(|k| k.as_str())
        .map(|k| k.trim().to_string())
        .filter(|k| !k.is_empty())
}

pub fn configurees(app: &AppHandle) -> bool {
    cle_publique(app).is_some()
}

fn adresse(canal: &str) -> Result<Url, String> {
    match canal {
        "stable" | "beta" => Url::parse(&format!("{DEPOT}/bureau-canal-{canal}/latest.json")).map_err(|e| e.to_string()),
        _ => Err("canal inconnu".into()),
    }
}

async fn chercher(app: &AppHandle, canal: &str) -> Result<Option<tauri_plugin_updater::Update>, String> {
    let cle = cle_publique(app).ok_or("mises à jour pas encore activées pour cette version")?;
    app.updater_builder()
        .pubkey(cle)
        .endpoints(vec![adresse(canal)?])
        .map_err(|e| e.to_string())?
        .build()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn verifier_mise_a_jour(app: AppHandle, canal: String) -> Result<Option<Value>, String> {
    Ok(chercher(&app, &canal).await?.map(|m| {
        json!({ "version": m.version, "notes": m.body, "date": m.date.map(|d| d.to_string()) })
    }))
}

#[tauri::command]
pub async fn installer_mise_a_jour(app: AppHandle, canal: String) -> Result<(), String> {
    let m = chercher(&app, &canal).await?.ok_or("aucune mise à jour")?;
    // Téléchargée, puis vérifiée par sa signature AVANT d'être installée ; une signature fausse arrête tout ici.
    m.download_and_install(|_, _| {}, || {}).await.map_err(|e| e.to_string())?;
    app.restart();
}

#[cfg(test)]
mod essais {
    use super::adresse;

    #[test]
    fn deux_canaux_seulement() {
        assert!(adresse("stable").unwrap().as_str().ends_with("/bureau-canal-stable/latest.json"));
        assert!(adresse("beta").unwrap().as_str().starts_with("https://github.com/wilnergraph92/speed-express-site/"));
        assert!(adresse("../../autre").is_err());
        assert!(adresse("").is_err());
    }
}
