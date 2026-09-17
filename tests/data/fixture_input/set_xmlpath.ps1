$f = "$env:APPDATA\Pioneer\rekordbox\rekordbox3.settings"
$s = Get-Content $f -Raw
$s = $s -replace 'bridgeImportedLibraryFile" val="[^"]*"', 'bridgeImportedLibraryFile" val="C:/rkb-fixtures/rekordbox.xml"'
$s = $s -replace 'showRbXml" val="0"', 'showRbXml" val="1"'
$s = $s -replace 'RekordboxXmlChecked" val="0"', 'RekordboxXmlChecked" val="1"'
Set-Content $f $s -NoNewline
Select-String -Path $f -Pattern 'bridgeImported|showRbXml|RekordboxXmlChecked' | ForEach-Object { $_.Line.Trim() }
