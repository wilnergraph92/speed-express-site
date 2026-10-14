//! Speed Express Operations — l'enveloppe Tauri 2 du tableau de bord (phase 10, ADR 0016).
//!
//! Les écrans sont les pages du site, embarquées telles quelles (bureau/preparer.mjs) : mêmes scripts, mêmes appels à la base
//! (les mêmes lg_* que le site et les applications mobiles), avec la clé PUBLIQUE de Supabase seulement. Ce fichier n'ajoute que
//! ce qu'un navigateur ne sait pas faire, en commandes étroites :
//!   · imprimer        — la boîte d'impression du système (macOS ; ailleurs, le navigateur l'ouvre lui-même) ;
//!   · imprimantes     — les imprimantes installées sur le poste ;
//!   · imprimer_brut   — l'étiquette ZPL envoyée telle quelle à UNE imprimante de cette liste ;
//!   · ouvrir_lien     — un lien https, mailto ou tel dans le navigateur du système ;
//!   · infos, verifier_mise_a_jour, installer_mise_a_jour — la version, et les mises à jour signées (stable ou bêta).
//! Aucun secret ici : ni clé de service de la base, ni clé de paiement, ni clé privée de mise à jour (seule la clé PUBLIQUE est embarquée).

mod impression;
mod majs;

use tauri::{Manager, Url, WebviewWindow};
use tauri_plugin_opener::OpenerExt;

/// Les seules adresses où la fenêtre a le droit d'aller : ses propres pages (macOS « tauri://localhost », Windows
/// « https://tauri.localhost »). Tout le reste est refusé, et un lien du web s'ouvre dans le navigateur du système.
fn adresse_interne(url: &Url) -> bool {
    match url.scheme() {
        "tauri" => url.host_str() == Some("localhost"),
        "http" | "https" => matches!(url.host_str(), Some("tauri.localhost")),
        _ => false,
    }
}

fn lien_externe_permis(url: &Url) -> bool {
    matches!(url.scheme(), "https" | "mailto" | "tel")
}

#[tauri::command]
fn imprimer(fenetre: WebviewWindow) -> Result<&'static str, String> {
    if cfg!(target_os = "macos") {
        fenetre.print().map_err(|e| e.to_string())?;
        Ok("systeme")
    } else {
        // WebView2 (Windows) ouvre sa propre boîte d'impression : la page appelle alors window.print() d'origine.
        Ok("navigateur")
    }
}

#[tauri::command]
async fn imprimantes() -> Result<Vec<String>, String> {
    tauri::async_runtime::spawn_blocking(impression::lister).await.map_err(|e| e.to_string())?
}

#[tauri::command]
async fn imprimer_brut(imprimante: String, donnees: String) -> Result<(), String> {
    if donnees.is_empty() || donnees.len() > 256 * 1024 {
        return Err("étiquette vide ou trop grande".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        // Seulement une imprimante que le système déclare : jamais un nom arbitraire venu de la page.
        let connues = impression::lister()?;
        if !connues.iter().any(|n| n == &imprimante) {
            return Err(format!("imprimante inconnue sur ce poste : {imprimante}"));
        }
        impression::brut(&imprimante, donnees.as_bytes())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
fn ouvrir_lien(app: tauri::AppHandle, url: String) -> Result<(), String> {
    let u = Url::parse(&url).map_err(|e| e.to_string())?;
    if !lien_externe_permis(&u) {
        return Err("lien refusé".into());
    }
    app.opener().open_url(u.as_str(), None::<&str>).map_err(|e| e.to_string())
}

#[tauri::command]
fn infos(app: tauri::AppHandle) -> serde_json::Value {
    serde_json::json!({
        "version": app.package_info().version.to_string(),
        "systeme": std::env::consts::OS,
        "architecture": std::env::consts::ARCH,
        "mises_a_jour": majs::configurees(&app),
    })
}

pub fn lancer() {
    let garde = tauri::plugin::Builder::<tauri::Wry, ()>::new("garde-navigation")
        .on_navigation(|webview, url| {
            if adresse_interne(url) {
                return true;
            }
            if lien_externe_permis(url) {
                let _ = webview.app_handle().opener().open_url(url.as_str(), None::<&str>);
            }
            false
        })
        .build();

    tauri::Builder::default()
        // Une seule fenêtre par poste : un second lancement ramène la première (deux postes de scan ouverts liraient deux fois).
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(f) = app.get_webview_window("principale") {
                let _ = f.unminimize();
                let _ = f.set_focus();
            }
        }))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(garde)
        .invoke_handler(tauri::generate_handler![
            imprimer,
            imprimantes,
            imprimer_brut,
            ouvrir_lien,
            infos,
            majs::verifier_mise_a_jour,
            majs::installer_mise_a_jour
        ])
        .run(tauri::generate_context!())
        .expect("Speed Express Operations n'a pas pu démarrer");
}

#[cfg(test)]
mod essais {
    use super::*;

    #[test]
    fn seules_les_pages_internes_sont_permises() {
        for ok in ["tauri://localhost/tableau-de-bord.html", "https://tauri.localhost/connexion.html", "http://tauri.localhost/x.html"] {
            assert!(adresse_interne(&Url::parse(ok).unwrap()), "{ok}");
        }
        for non in ["https://evil.example/", "https://tauri.localhost.evil.example/", "tauri://autre/", "file:///etc/passwd", "javascript:alert(1)"] {
            assert!(!adresse_interne(&Url::parse(non).unwrap()), "{non}");
        }
    }

    #[test]
    fn liens_externes_limites() {
        assert!(lien_externe_permis(&Url::parse("https://wa.me/18292653727").unwrap()));
        assert!(lien_externe_permis(&Url::parse("mailto:a@b.c").unwrap()));
        assert!(!lien_externe_permis(&Url::parse("http://exemple.test/").unwrap()));
        assert!(!lien_externe_permis(&Url::parse("file:///C:/Windows/").unwrap()));
        assert!(!lien_externe_permis(&Url::parse("smb://serveur/partage").unwrap()));
    }
}
