# ...


### Show progress

While uploading, the progress can be viewed by doing the following query against the database file:

```
select printf('%.2f %%', avg(uploaded)*100) as progress from files;
```
