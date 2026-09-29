1. install [git](https://git-scm.com/install/windows)
1. install and setup `azcopy`
1. install [uv](https://docs.astral.sh/uv/getting-started/installation/)
1. open `Git Bash` and run

```bash
cd $HOME
git clone https://github.com/SurgeonDecisionIntelligence/quality-labeler.git
azcopy cp --recursive https://tissueconnectstorage.blob.core.windows.net/joshfisher/Irina/QCLabeler/ .
cd QCLabeler
uv run download_qc.py lineage_092126.csv $HOME/Pictures/QC
```

1. After all the images download, open `Git Bash` and run

```base
cd $HOME/quality-labeler
uv run quality-labeler label $HOME/Pictures/QC
```
