let
    Root = Text.TrimEnd(pProjectRoot, {"\", "/"}),
    Gen = if Text.Upper(Text.Trim(pGeneration)) = "CURRENT"
       then Text.Trim(Text.FromBinary(File.Contents(Root & "\data\processed\p3_3\CURRENT"), TextEncoding.Utf8))
       else Text.Trim(pGeneration),
    Manifest = Json.Document(File.Contents(Root & "\data\processed\p3_3\generations\" & Gen & "\generation_manifest.json")),
    Rows = #table({"generation_id", "official_asof", "marketplace_asof"}, {{
       Gen, Date.FromText(Manifest[source_asof][OFFICIAL]), Date.FromText(Manifest[source_asof][MARKETPLACE])}}),
    Typed = Table.TransformColumnTypes(Rows, {{"generation_id", type text}, {"official_asof", type date}, {"marketplace_asof", type date}})
in
    Typed
