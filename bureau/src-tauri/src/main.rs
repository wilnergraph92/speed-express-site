// Speed Express Operations — le point d'entrée. Sous Windows, pas de console derrière la fenêtre en version publiée.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    ses_operations_lib::lancer();
}
