import glob

for f in glob.glob('d:/Projects/BillLens/frontend/src/pages/*.tsx') + ['d:/Projects/BillLens/frontend/src/App.tsx']:
    with open(f, 'r', encoding='utf-8') as file:
        c = file.read().replace("import React from 'react';\n", "")
    with open(f, 'w', encoding='utf-8') as file:
        file.write(c)

with open('d:/Projects/BillLens/frontend/src/hooks/useRunStream.ts', 'r', encoding='utf-8') as file:
    c = file.read().replace("import { useEffect, useState, useRef } from 'react';", "import { useEffect, useState } from 'react';")
with open('d:/Projects/BillLens/frontend/src/hooks/useRunStream.ts', 'w', encoding='utf-8') as file:
    file.write(c)
