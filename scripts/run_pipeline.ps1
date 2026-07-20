param(
    [ValidateSet("catalog", "pilot")]
    [string]$Profile = "pilot"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

function Invoke-Aura {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & python -m aura_corpus @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "aura-corpus exited with code $LASTEXITCODE"
    }
}

Invoke-Aura sources
Invoke-Aura catalog --max-candidates 2000 --max-pages 40

if ($Profile -eq "catalog") {
    exit 0
}

Invoke-Aura fetch --source gene_ontology --source reactome_summaries --source mesh_descriptors --source pubmedqa_labeled --source pubmedqa_test_ground_truth --yes
Invoke-Aura fetch --source pubmed_baseline --max-files 2 --allow-bulk --yes
Invoke-Aura fetch --source pmc_oa_comm_xml --max-files 25 --allow-bulk --yes
Invoke-Aura fetch --source nlm_litarch_biology --max-files 5 --allow-bulk --yes
Invoke-Aura verify
Invoke-Aura status
