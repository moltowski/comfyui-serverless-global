"""
PT Input Hub — UN seul noeud-contrat pour les project types.

Idee (reunion Vlad/Lee) : UN meganode "thin" par workflow qui porte tous les inputs
pilotables par l'app + des switches/compteurs d'activation. Il NE CHARGE RIEN : il
emet des valeurs finales (strings/chemins/nombres) qu'on branche DIRECTEMENT sur les
noeuds DEJA presents du workflow.

L'app trouve le noeud par son class_type ("PT_InputHub") et ecrit ses champs ; elle
ne fouille jamais le graphe. La resolution nom+version -> fichier et la logique
d'activation (enable off -> strength 0 / chemin vide) se font cote app AVANT d'ecrire
le hub ; le hub reste un pur porteur de valeurs.

=== SCHEMA — versioning APPEND ONLY ===
L'ORDRE des sorties est le CONTRAT (l'app cable par indice). Regle de versioning :
- Modification = APPEND ONLY. On n'insere/ne reordonne/ne supprime JAMAIS un champ
  existant (ca casserait les indices des workflows deja cables). Tout nouveau champ
  va A LA FIN, et on bump SCHEMA_VERSION.
- SCHEMA_VERSION est lisible par l'app (defaut du champ `schema_version` visible dans
  /object_info) pour savoir a quel contrat elle a affaire.
Voir SCHEMA.md pour la table complete indice<->champ.

Historique :
- v1 (2026-09-02) : 28 champs (prompt..schema_version).
- v2 (2026-09-07) : + `duration` (secondes, modeles type H3) + `frames` (nb d'images,
  modeles type WAN). Ajoutes A LA FIN -> indices 28 et 29 ; les indices 0..27 sont
  inchanges. Un workflow ne cable QUE l'unite de son modele (H3=duration, WAN=frames).

Deux classes de loaders pour les REFS (valide sur pod 2026-09-02) :
- Les noeuds d'UPLOAD core (LoadImage/LoadAudio/VHS_LoadVideo) ont un VALIDATE_INPUTS
  qui plante quand l'entree est un lien (valeur None) -> INUTILISABLES en hub-driven.
- Les loaders PAR CHEMIN (WAS "Image Load", VHS_LoadVideoPath) prennent un STRING ->
  le hub les pilote. C'est l'usage prevu : le hub porte des CHEMINS, pas des uploads.
Les champs qui alimentent un widget COMBO (lora_name*, aspect_ratio) sortent en type
wildcard ANY (cf. _AnyType) pour passer la validation de type de ComfyUI.
"""

# Ratios (repris de Image-api-connector, Nano Banana / Seedream...). Certains modeles
# API prennent un RATIO, pas un width/height.
_NANO_AR = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9",
            "1:4", "4:1", "1:8", "8:1", "match_input_image"]

# Plafonds refs = format Ref2VA MiniMax H3 (9 images + 2 audio + 2 video).
N_IMG, N_AUD, N_VID = 9, 2, 2

SCHEMA_VERSION = 2


class _AnyType(str):
    """Type wildcard : egal a n'importe quel type ComfyUI a la validation.

    Permet de brancher une sortie du hub sur un widget COMBO d'un noeud core
    (LoraLoader.lora_name, ratio d'un modele API...). ComfyUI compare les types au
    lien : STRING -> COMBO leve `return_type_mismatch` (verifie pod 0.33). En rendant
    `!=` toujours faux, ce type passe la validation ; a l'execution le noeud recoit la
    string et la resout normalement. Meme mecanisme que rgthree / Impact Pack.
    """

    def __ne__(self, other):
        return False


ANY = _AnyType("*")


def _build_spec():
    """(name, in_def, out_type) dans l'ORDRE DU CONTRAT. Append-only apres freeze."""
    STR_ML = ("STRING", {"multiline": True, "default": ""})
    STR = lambda d="": ("STRING", {"default": d})
    INT = lambda d=0, mn=0, mx=0xffffffffffffffff: ("INT", {"default": d, "min": mn, "max": mx})
    FLT = ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05})
    BOOL = ("BOOLEAN", {"default": True})
    s = []
    # -- texte / params --
    s += [("prompt", STR_ML, "STRING")]
    s += [("seed", INT(), "INT")]
    s += [("width", INT(1024, 64, 8192), "INT")]
    s += [("height", INT(1024, 64, 8192), "INT")]
    s += [("aspect_ratio", (_NANO_AR, {"default": "1:1"}), ANY)]  # peut viser un COMBO
    s += [("out_prefix", STR("project/out"), "STRING")]
    # -- LoRA : 2 slots (identite + concept/action). Nom de FICHIER final (resolu app). --
    s += [("lora_name", STR(""), ANY)]
    s += [("lora_strength", FLT, "FLOAT")]
    s += [("lora_name_2", STR(""), ANY)]
    s += [("lora_strength_2", FLT, "FLOAT")]
    # -- refs = CHEMINS deja presents dans input/ du pod (a brancher sur des path-loaders) --
    for i in range(N_IMG):
        s += [(f"ref_image_{i}", STR(""), ANY)]
    for i in range(N_AUD):
        s += [(f"ref_audio_{i}", STR(""), ANY)]
    for i in range(N_VID):
        s += [(f"ref_video_{i}", STR(""), ANY)]
    # -- form-spec : combien de refs ce workflow consomme (l'app affiche le bon nb de slots) --
    s += [("n_ref_images", INT(0, 0, N_IMG), "INT")]
    s += [("n_ref_audio", INT(0, 0, N_AUD), "INT")]
    s += [("n_ref_video", INT(0, 0, N_VID), "INT")]
    s += [("enable_character", BOOL, "BOOLEAN")]
    # -- version du schema (lisible par l'app) --
    s += [("schema_version", INT(SCHEMA_VERSION, 0, 9999), "INT")]
    # === v2 (append-only) : duree video ===
    # duration = SECONDES (modeles qui pensent en secondes, ex. MiniMax H3).
    # frames   = NB D'IMAGES (modeles qui pensent en frames, ex. WAN : length 4n+1).
    # Un workflow ne cable QUE le champ de son modele ; les images n'en cablent aucun.
    s += [("duration", ("FLOAT", {"default": 5.0, "min": 0.0, "max": 60.0, "step": 0.5}), "FLOAT")]
    s += [("frames", INT(81, 1, 100000), "INT")]
    return s


_SPEC = _build_spec()


class PT_InputHub:
    """Le seul noeud nouveau. Centralise tous les inputs + form-spec. Thin (n'execute rien)."""

    SCHEMA_VERSION = SCHEMA_VERSION

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {name: in_def for (name, in_def, _out) in _SPEC}}

    RETURN_TYPES = tuple(out for (_n, _i, out) in _SPEC)
    RETURN_NAMES = tuple(name for (name, _i, _o) in _SPEC)
    FUNCTION = "emit"
    CATEGORY = "project_types"

    def emit(self, **kw):
        # renvoie les valeurs dans l'ordre exact du contrat
        return tuple(kw[name] for (name, _i, _o) in _SPEC)


NODE_CLASS_MAPPINGS = {"PT_InputHub": PT_InputHub}
NODE_DISPLAY_NAME_MAPPINGS = {"PT_InputHub": "Project Type — Input Hub"}
