#include "metabrowser/conversation_store.h"
#include <algorithm>
#include <cstdlib>
#include "base/files/file_enumerator.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/task/thread_pool.h"
#include "base/task/sequenced_task_runner.h"
#include "base/uuid.h"
namespace metabrowser {
namespace {
scoped_refptr<base::SequencedTaskRunner> Writer(){
  static auto* writer=new scoped_refptr<base::SequencedTaskRunner>(base::ThreadPool::CreateSequencedTaskRunner({base::MayBlock(),base::TaskPriority::USER_VISIBLE,base::TaskShutdownBehavior::BLOCK_SHUTDOWN}));return *writer;
}
bool Valid(const std::string& id){return base::Uuid::ParseLowercase(id).is_valid();}
bool Prepare(const base::FilePath& root){return base::CreateDirectory(root)&&base::SetPosixFilePermissions(root,0700);}
}
base::FilePath ConversationStore::Root(){
  const char* override=getenv("METABROWSER_CONVERSATION_HOME");if(override&&*override)return base::FilePath(override);
  const char* home=getenv("HOME");return base::FilePath(home?home:"").AppendASCII("Library/Application Support/MetaBrowser/conversations");
}
base::DictValue ConversationStore::Load(const std::string& id){
  if(!Valid(id))return {};std::string bytes;
  if(!base::ReadFileToStringWithMaxSize(Root().AppendASCII(id+".json"),&bytes,32*1024*1024))return {};
  auto value=base::JSONReader::ReadDict(bytes,base::JSON_PARSE_RFC);if(!value||!value->FindString("id")||*value->FindString("id")!=id)return {};return std::move(*value);
}
std::vector<base::DictValue> ConversationStore::List(){
  std::vector<std::pair<base::Time,std::string>> paths;base::FileEnumerator files(Root(),false,base::FileEnumerator::FILES,FILE_PATH_LITERAL("*.json"));
  for(auto file=files.Next();!file.empty();file=files.Next())paths.emplace_back(files.GetInfo().GetLastModifiedTime(),file.BaseName().RemoveExtension().value());
  std::sort(paths.rbegin(),paths.rend());std::vector<base::DictValue> records;
  for(const auto& [time,id]:paths){auto value=Load(id);if(!value.empty())records.push_back(std::move(value));if(records.size()>=100)break;}return records;
}
void ConversationStore::Save(base::DictValue record){
  const auto* id=record.FindString("id");if(!id||!Valid(*id))return;auto encoded=base::WriteJson(record);if(!encoded)return;
  Writer()->PostTask(FROM_HERE,base::BindOnce([](base::FilePath root,std::string id,std::string bytes){
    if(!Prepare(root))return;const auto destination=root.AppendASCII(id+".json"),temporary=root.AppendASCII(id+".tmp");
    if(base::WriteFile(temporary,bytes)&&base::SetPosixFilePermissions(temporary,0600))base::ReplaceFile(temporary,destination,nullptr);
  },Root(),*id,std::move(*encoded)));
}
void ConversationStore::Event(const std::string& id,std::string encoded){
  if(!Valid(id))return;
  // Serial appends retain original SDK records, including unknown event tags.
  Writer()->PostTask(FROM_HERE,base::BindOnce([](base::FilePath root,std::string id,std::string bytes){
    if(!Prepare(root))return;const auto path=root.AppendASCII(id+".events.jsonl");
    if(!base::PathExists(path)){if(!base::WriteFile(path,""))return;}
    if(!base::SetPosixFilePermissions(path,0600))return;base::AppendToFile(path,bytes+"\n");
  },Root(),id,std::move(encoded)));
}
}
